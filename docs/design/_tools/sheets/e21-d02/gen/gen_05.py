"""Board 05 stale-disconnected: SCR-050/stale (T1 and the ≥ T2 step) and SCR-050/disconnected (§4; SR-038);
dark, exported again under light (the twin)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 5


def stale(t2: bool) -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/stale" + (" · ≥ T2" if t2 else "")
    p = ui.P(state="stale-t2" if t2 else "stale")
    age = k.STALE_T2_AGE if t2 else k.STALE_T1_AGE
    k.derive(f"stale age {age} s: last update {k.hms(k.NOW, age)} at {k.hms(k.NOW)} UTC; T1 {k.T1_S} s, T2 = 3 × T1 "
             f"= {k.T2_S} s (§4)")
    if not t2:
        k.spec_gap(f"the T1 frame draws W-5 \"{k.W('W-5')}\" and W-6 \"{k.W('W-6')}\" verbatim (their example age "
                   f"{age} s), yet §4 puts {age} s at ≥ T2 = 3 × T1 = {k.T2_S} s: the copy deck's figure and §4's "
                   f"thresholds disagree; the frame keeps the T1 treatment (chip, feed.stale) — the spec owner to "
                   f"re-figure W-5 / W-6 or the threshold")
    ann = ui.announce(k.W("W-6") if not t2 else
                      k.ui("the workspace's one assertive sentence (D02E17:256)", "the announcement is E17-D02's"),
                      how="polite, once on entry" if not t2 else "assertive, once (the workspace's; the panel adds "
                      "none)")
    return ui.panel(fid, p, markers=[ann]), k.frame_block(fid, [
        ("≥ T2: the strong chip W-26 and the notice leads with feed.stale_t2 (W-27); W-6 is the T1 line (§4), not "
         "redrawn with this age" if t2 else
         "T1: stale shading, the W-5 chip and W-6; the notice leads with feed.stale (W-8)") +
        "; the chip's age is aria-live=\"off\" (it ticks visually only)",
        "SR-038: a frozen book never reads live — the header text state and the notice; stale ≥ T1 drops the "
        "one-click arm (D01E17:203); in E21 the pill is LOCKED throughout", "W-29 polite once on exit"])


def disconnected() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/disconnected"
    p = ui.P(state="disconnected")
    k.derive(f"disconnected: last data {k.hms(k.DISC_LAST)} UTC (W-7's minute)")
    return ui.panel(fid, p), k.frame_block(fid, [
        "The ladder frozen with its values, stale tokens; W-7 in the header; the notice leads with feed.disconnected "
        "(W-9); nothing moves under focus",
        "Announced: none from the panel — CMP-077's assertive alert is the one announcement (D02E17:253) and its "
        "recovery alert the exit (D02E17:264)"])


if __name__ == "__main__":
    ui.run(NN, [stale(False), stale(True), disconnected()], 3)
