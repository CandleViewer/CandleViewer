"""Board 07 `E12-D07 / 07 sync-and-edge`: sync/before-loaded, sync/stale-banner-non-time (tick, dark, strip)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pair3_helpers import HL, L, SL, fit_frame, is_sep, k  # noqa: E402

NN = 7
FIDS = k.BOARDS[NN].frames  # ("sync/before-loaded · dark", "sync/stale-banner-non-time · dark")
MODE = "tick"
LOADED_FROM = "10:00"  # the loaded window's first bar: older pages not yet fetched (a page is in flight)


def before_loaded() -> tuple[dict, tuple[str, list[str]]]:
    fid = FIDS[0]
    s = k.series(MODE)
    i0 = k.at(MODE, LOADED_FROM)
    first = s[i0]
    seq = [("sep", "loading-older", {})] + s[i0:]
    r = fit_frame(fid, MODE, seq, start=0, loaded=len(s) - i0, rows_all=s, older=True, focus=lambda x: x is first)
    s91 = L("### 9.1 Sync")
    extra = [
        f"Trigger (not visible: the chart is hidden while the table is open in place, reading A-7): the chart's "
        f"cursor went before the first loaded bar; the table focuses the first loaded row and never jumps to another "
        f"row (§9.1 L{L('**Before the loaded window.**')})",
        f"Boundary row: E11-D04's loading-older band \"{k.E11_BANDS['loading-older']}\" above the first row, "
        f"unchanged (§7.1 L{L('| loading older bars ')}; D04E11:{SL('| **loading older bars**')}), with CMP-053 "
        f"Older in the footer; band-row form §7.2 L{L('### 7.2 The band-row form')}",
        f"Rows: the loaded window starts at {k.row_header(first, MODE)} ({len(s) - i0} bars loaded, older pages "
        f"in flight); focus on that first row, under its boundary row (hand-off L{HL('Board 07: moving before')})",
    ]
    blk = k.frame_block(
        fid, state=f"sync/before-loaded (§9.1 L{s91}: the cursor before the loaded window)", mode=MODE,
        cols=r["cols"], row_header_form=f"{k.row_header(first, MODE)} — name: {k.row_name(first, MODE)}",
        keyboard=f"the chart's cursor moved (origin pointer / keyboard on the chart); the table focus follows at most "
                 f"once per frame (§9.1 L{L('**Coalesced.**')}); Ctrl+Home raises one history page (D04E11:263); "
                 f"↑ from the first row stops on the band row",
        announcement=f"polite, once: \"{k.copy('W-16')}\" (W-16; §9.1)",
        copy_keys=("W-10", "W-11", "W-16"), tokens=(), extra=extra)
    return r["frame"], blk


def stale_banner() -> tuple[dict, tuple[str, list[str]]]:
    fid = FIDS[1]
    s = k.series(MODE)
    i0 = k.at(MODE, "10:22:11.412") - 6
    chars = k.stale_banner_text(mode=MODE)
    r = fit_frame(fid, MODE, s, start=i0, loaded=len(s), banner_chars=chars,
                  focus=lambda b: not is_sep(b) and b.t == k.SWEEP_AT and b.k == 3)
    f = r["focus"]
    b7 = SL("## 7. The stale banner")
    extra = [
        f"Banner: CMP-028 warning banner between the filter line and the header, warning.subtle fill, warning.strong "
        f"glyph, the Shift+R Kbd and Refresh to current (D04E11:{b7}–{SL('**Announcement.** Polite')}); words = W-22 "
        f"+ E11-D04's tail \"{k.STALE_TAIL.strip()}\" (§9.1 L{L('**After the view moves on.**')})",
        f"Rows: the focused bar {k.row_header(f, MODE)} keeps aria-current; it left the chart's visible range because "
        f"the chart moved (D04E11 §7 condition); row values keep patching",
        "Refresh: Shift+R or the button scrolls to the chart's range, focuses the latest visible bar and announces "
        "\"Refreshed to current: row k of N\" (D04E11 §7, unchanged)",
    ]
    blk = k.frame_block(
        fid, state=f"sync/stale-banner-non-time (§9.1 L{L('**After the view moves on.**')}: banner names a non-time bar)",
        mode=MODE, cols=r["cols"], row_header_form=f"{k.row_header(f, MODE)} — name: {k.row_name(f, MODE)}",
        keyboard="focus stays on the bar 3 of 5 row (2 px color.focus.ring); Shift+R (grid focused) refreshes to "
                 "current; Esc or Alt+T back to the chart",
        announcement=f"polite, once on appearance (D04E11:{SL('**Announcement.** Polite')}), E11-D04's form with the "
                     f"bar named by its row header: \"Table is on bar {k.row_header(f, MODE)}, which is no longer in "
                     f"view on the chart.\"",
        copy_keys=("W-10", "W-11", "W-22"), tokens=(), extra=extra)
    return r["frame"], blk


def build() -> None:
    frames, blocks, toks = [], [], set()
    for fn in (before_loaded, stale_banner):
        fr, blk = fn()
        frames.append(fr)
        blocks.append(blk)
        toks |= set(k.frame_tokens(fr))
    b = k.BOARDS[NN]
    ann = k.annotations(NN, blocks, board_lines=[
        f"Owner walkthrough item (hand-off L{HL('Board 07: moving before')}): moving before the loaded window lands "
        "on the first loaded row under its boundary row",
        "Tokens (every frame binds from this set): " + ", ".join(sorted(toks))])  # live-check fold: the old data line is superseded by data-line
    k.live("frame 1: read back the band row \"Loading older bars…\" directly above the first bar row, the first bar row "
           "carrying the only 2 px color.focus.ring, and the footer's Older control")
    k.live("frame 2: read back the banner text exactly \"Data is for bar 10:22:11.412 bar 3 of 5, no longer in view — "
           "press Shift+R or Refresh to current\" on one line, fill color.status.warning.subtle, h 32")
    k.live("frame 2: read back the focused row's header \"10:22:11.412 bar 3 of 5\" with the 2 px ring")
    notes = {
        "spec_gaps": [
            "A-7: the chart is hidden while the table is open in place, so sync/before-loaded draws the table state "
            "only (first loaded row focused under the loading-older band) and states the trigger in the annotation",
            "the boundary row is the loading-older band because W-16 says \"Loading older bars\"; the hand-off allows "
            "lookback or loading-older",
            "the stale banner's polite announcement on a non-time series is not given verbatim by the spec (§9.1 "
            "names only the banner, W-22); the annotation applies E11-D04's form with the row header in place of the "
            "time, as W-22 does for the banner; not drawn",
            "A-8: rows come from a seeded synthetic stream; only tick size and qty step come from the fixture"],
    }
    path = k.write_sheet(NN, frames, ann, notes=notes)
    k.write_md(NN, path, frames_info=[
        f"sources: spec §0 L{b.line}; §2.2 L{L('### 2.2 Non-time bars')}; §7.1 L{L('### 7.1')}; §7.2 "
        f"L{L('### 7.2 The band-row form')}; §9.1 L{L('### 9.1 Sync')}; §13 W-16 L{k.COPY['W-16'][1]}, W-22 "
        f"L{k.COPY['W-22'][1]}, W-10 L{k.COPY['W-10'][1]}, W-11 L{k.COPY['W-11'][1]}; E11-D04 §7 L{SL('## 7. The stale')}, "
        f"loading-older L{SL('| **loading older bars**')}; hand-off §H L{HL('| 07    |')}",
        f"theme dark; export {b.export}"])
    print(path, k.pack_sheet(path))


if __name__ == "__main__":
    build()
