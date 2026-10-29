"""E42-D04 cap10b board 02 `scr135-tamper-failed` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  row 1: AL-13 · 1280×800 [13] <- gen/gen_13.py node 'frame-1280' · AL-13 · 2560×1440 [13] <- gen/gen_13.py node 'frame-2560' · AD-5 · 1280×800 [34] <- gen/gen_34.py node 'frame-1280'
  row 2: AL-14 · 1 strip (SCR-148) · 1280×800 [14] <- gen/gen_14.py node 'frame-1280 · 1 strip (SCR-148)' · AL-14 · 2 tile (SCR-120) · 1280×800 [14] <- gen/gen_14.py node 'frame-1280 · 2 tile (SCR-120)' · AL-14 · 3 row (SCR-144) · 1280×800 [14] <- gen/gen_14.py node 'frame-1280 · 3 row (SCR-144)'

Each frame is the old board's frame tree as its generator built it (E42-D04/NN-<slug>.json, read only; harvest.json
records whether the generator still re-runs on its pinned spec and matches; BUILD.md). Writes ../cap10b/02-scr135-tamper-failed.json
+ .md (validated, exit 0) and packs ../v4/02-scr135-tamper-failed.json with compact.py.
Usage: python3 -I -B gen10/02-scr135-tamper-failed.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cap10  # noqa: E402

NN = 2

if __name__ == "__main__":
    raise SystemExit(cap10.main_one(NN))
