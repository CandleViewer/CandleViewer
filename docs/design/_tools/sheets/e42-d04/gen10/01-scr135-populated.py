"""E42-D04 cap10b board 01 `scr135-populated` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  row 1: AL-2 · 1280×800 [02] <- gen/gen_02.py node 'frame-1280' · AL-2 · 2560×1440 [02] <- gen/gen_02.py node 'frame-2560' · AL-3 · 1280×800 [03] <- gen/gen_03.py node 'frame-1280'
  row 2: AL-18 · 1280×800 [18] <- gen/gen_18.py node 'frame-1280' · AL-20 · 1280×800 [20] <- gen/gen_20.py node 'frame-1280' · AL-21 · 1280×800 [21] <- gen/gen_21.py node 'frame-1280'

Each frame is the old board's frame tree as its generator built it (E42-D04/NN-<slug>.json, read only; harvest.json
records whether the generator still re-runs on its pinned spec and matches; BUILD.md). Writes ../cap10b/01-scr135-populated.json
+ .md (validated, exit 0) and packs ../v4/01-scr135-populated.json with compact.py.
Usage: python3 -I -B gen10/01-scr135-populated.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cap10  # noqa: E402

NN = 1

if __name__ == "__main__":
    raise SystemExit(cap10.main_one(NN))
