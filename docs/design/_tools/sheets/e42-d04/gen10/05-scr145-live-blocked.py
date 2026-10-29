"""E42-D04 cap10b board 05 `scr145-live-blocked` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  row 1: FF-2 · 1280×800 [39] <- gen/gen_39.py node 'frame-1280' · FF-2 · 2560×1440 [39] <- gen/gen_39.py node 'frame-2560'
  row 2: FF-4 · 1280×800 [41] <- gen/gen_41.py node 'frame-1280' · FF-4 · 2560×1440 [41] <- gen/gen_41.py node 'frame-2560'

Each frame is the old board's frame tree as its generator built it (E42-D04/NN-<slug>.json, read only; harvest.json
records whether the generator still re-runs on its pinned spec and matches; BUILD.md). Writes ../cap10b/05-scr145-live-blocked.json
+ .md (validated, exit 0) and packs ../v4/05-scr145-live-blocked.json with compact.py.
Usage: python3 -I -B gen10/05-scr145-live-blocked.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cap10  # noqa: E402

NN = 5

if __name__ == "__main__":
    raise SystemExit(cap10.main_one(NN))
