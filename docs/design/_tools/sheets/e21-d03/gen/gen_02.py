"""Board 02 tier-rebuild-500: SCR-051/tier-change-pending, /saving, /rebuild-refused, /500-unavailable (§3.1, §3.2,
§8.1–§8.3) and D02's tier notice inset (W-5, W-36 after Save)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 1 + 1


def pending() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/tier-change-pending"
    d = ui.Dlg(tier=500, w4=True, focus="tier 500", extra=[ui.announce(k.W("W-4"))])
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        "200 → 500 picked, not saved: a book key (R-2), so W-4 shows under the group at once, as plain text in the "
        "tabpanel; the tile already shows the 500 sample (R-1); nothing applies to the panel before Save",
        f"Tile at 500: each band sums 100 levels; stops {', '.join(k.size_fmt(a) for a in k.stops(500))} BTC (adaptive)",
        "A second book key changed in the same session does not repeat W-4 (R-5: an equal queued message is dropped)"])


def saving() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/saving"
    d = ui.Dlg(tier=500, w4=True, save="busy", focus="save", status=k.W("W-38"), extra=[ui.announce(k.W("W-38"))])
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        "Save validated, the ctl sent: CMP-043 busy until ctl_ok (`23`:719); Save keeps focus with aria-disabled=\"true\" "
        "(never disabled), the body aria-busy=\"true\", every field aria-disabled=\"true\" (§8.2)",
        f"The status node writes W-38 once (R-5); no answer within the client's request timeout (G-6) ends the busy "
        f"state and §8.3 applies with W-9",
        "On ctl_ok the dialog closes, focus returns to the opener (else the panel's depth control, else the pane), the "
        "panel shows D02's tier notice (the inset); dom.depth_tier_changed fires on this Save (§14.1), with "
        "dom.settings_changed {key} per changed key"])


def refused() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/rebuild-refused"
    d = ui.Dlg(tier=500, w4=True, refused=k.W("W-9"))
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        "resync_rate_limited (`23`:731) or the deep-book cap (`23`:765) at Save: nothing changes; the dialog stays, "
        "the values are kept, the busy state ends (§8.3)",
        "W-9 inline under the Save row with focus moved to it (tabindex=\"-1\", no role=\"alert\": focus reads it); "
        "T4 at the point of action, not T2",
        "W-9 is the key book.rebuild_refused: PROPOSED for E17-D01 §7's owner (D03E17:211 routes the refused-ctl copy "
        "there)"])


def unavailable() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/500-unavailable"
    w3 = k.W("W-3")
    d = ui.Dlg(t2_500=True, focus="tier 500", extra=[ui.announce(w3, how="polite, on each Space / Enter (G-T2.3)")])
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        f"heatmap_depth_500 off (`24`:5615) or a cap: the 500 radio is T2 in rendering 2a (R-3): in the group, "
        f"aria-disabled=\"true\", never disabled, the CMP-019 lock leading the label, W-3 under the option "
        f"({len(w3)} characters) in the DOM at mount via aria-describedby, the well color.surface.raised + "
        f"color.border.default",
        "Arrowing lands on the 500 radio and focuses it without checking it: 200 stays checked; Space / Enter re-shows "
        "W-3 with one polite announcement (G-T2.3)",
        "W-3 is D02's key book.tier_unavailable, the same key (C-13): PROPOSED, vocabulary owner E09-D09 #192, "
        "\"if #5488 merges as is\"; OQ-1: a cap from E21-K01 #603 makes this the default, no redraw"])


def inset() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.INSET
    w5 = k.W("W-5")
    w36 = k.W("W-36", setting=k.S("Columns"), **{"from": k.S("1 s"), "to": k.S("500 ms")})
    k.derive("W-36 filled for a Columns change 1 s → 500 ms (kit choice of the example)")
    head = ui.backdrop(500)[0]
    fr_w = 1280
    # inside the marker frame the header spans its content width, the frame less 24 px padding a side (it kept the
    # window's 1280 and ran 24 px past the frame: SHEET-FIX 02)
    head = dict(head, w=fr_w - 2 * k.PX[k.INSET_XL])
    chip = k.hbox("D02 tier notice (W-5)", [k.icon("glyph", "pending", k.TEXT_2, k.ICON),
                                             k.text("words", w5, k.CAPTION, k.TEXT_1)],
                  {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.RAISED, "radius": k.R_CONTROL}, h=24)
    chip2 = k.hbox("panel pending chip (W-36)", [k.icon("glyph", "pending", k.TEXT_2, k.ICON),
                                                  k.text("words", w36, k.CAPTION, k.TEXT_1)],
                   {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.RAISED, "radius": k.R_CONTROL}, h=24)
    fr = k.marker_frame(fid, [
        k.text("lead", k.ui("After ctl_ok, until the fresh snap applies: the panel's pending text (E21-D02's notice)",
                            "board-marker caption"), k.LABEL, k.TEXT_1),
        {a: b for a, b in head.items() if a not in ("x", "y")}, chip,
        k.text("lead 2", k.ui("A row-aggregation or Columns change: the panel's pending chip", "board-marker caption"),
               k.LABEL, k.TEXT_1), chip2], fr_w)
    return fr, k.frame_block(fid, [
        f"W-5 is D02's tier notice verbatim (D02:402); W-36 its form for row aggregation and Columns (D03E17:208) — "
        f"never D02's resync scrim, never Stale or Resyncing (§8.2)",
        "kit choice: the notice drawn as a color.surface.raised chip with the local 'pending' glyph; its tokens and "
        "motion are E21-D02's and E21-D05's"])


if __name__ == "__main__":
    built = [pending(), saving(), refused(), unavailable(), inset()]
    k.build(NN, [x[0] for x in built], [x[1] for x in built], 2,
            board_lines=["Owner walkthrough items 2 and 3 (§18): the rebuild named before Save; the 500 option read "
                         "with the keyboard", "AD-7 (§14.2): the 200 default and the tier notice, with board 09"])
    print("ok", k.BOARDS[NN].sheet)
