"""Board 05 trading-demo-live: SCR-051/trading-demo, /trading-live, /live-confirm-off (§6; C-2.11); dark, exported
again under light (the twin)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 5
COMMON = ("The two confirm rules are separate lines, never one toggle across environments: W-18 (LIVE, a CMP-005, on "
          "by default, T Sec) and W-19 (DEMO, a text line, PROPOSED: C-14, owner E30-D04 / E31); each applies to its "
          "own environment only")


def demo() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/trading-demo"
    d = ui.Dlg(tab="Trading", env="DEMO")
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        f"Badge DEMO from the session (R-4), in the dialog's name: \"{k.W('W-2', symbol=k.SYM, env='DEMO')}\"",
        COMMON, "Quantity presets 0.1 · 0.25 · 0.5 · 1 BTC (`14`:1241); W-30 read-only with Ctrl+Shift+T; prefs only — "
        "nothing here places, amends or cancels an order (E21 has no order path)"])


def live() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/trading-live"
    d = ui.Dlg(tab="Trading", env="LIVE")
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        f"Badge LIVE from the session (R-4): \"{k.W('W-2', symbol=k.SYM, env='LIVE')}\"; the same lines as DEMO",
        "The environment is switched by SCR-074 / SCR-075 (`14`:81), never here; switching to LIVE takes C-2.11's "
        "typed confirm"])


def confirm_off() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/live-confirm-off"
    d = ui.Dlg(tab="Trading", env="LIVE", live_confirm=False, focus="live confirm",
               extra=[ui.announce(k.W("W-20"))])
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        "W-18 unchecked in a LIVE session: W-20 in a CMP-028 warning inline under it, no modal; re-checking removes "
        "it; focus stays on the checkbox",
        "No step-up to turn it off: PROPOSED, the inline warning only (C-14; owner E30-D04 / E31); no frame shows the "
        "warning under a DEMO badge"])


if __name__ == "__main__":
    ui.run(NN, [demo(), live(), confirm_off()], 2, board_lines=[
        "C-2.11: the badge reads the session environment, never the feed; DEMO and LIVE are separate frames",
        "Owner walkthrough item 6 (§18): could the LIVE confirm line be read as applying to DEMO"])
