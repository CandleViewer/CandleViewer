"""E42-D04 cap10b board 04 `scr136-detail` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  row 1: AD-1 · 1280×800 [30] <- gen/gen_30.py node 'frame-1280' · AD-1 · 2560×1440 [30] <- gen/gen_30.py node 'frame-2560' · AD-7 · 1280×800 [36] <- gen/gen_36.py node 'frame-1280'

Each frame is the old board's frame tree as its generator built it (E42-D04/NN-<slug>.json, read only; harvest.json
records whether the generator still re-runs on its pinned spec and matches; BUILD.md). Writes ../cap10b/04-scr136-detail.json
+ .md (validated, exit 0) and packs ../v4/04-scr136-detail.json with compact.py.
Usage: python3 -I -B gen10/04-scr136-detail.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cap10  # noqa: E402

NN = 4

if __name__ == "__main__":
    raise SystemExit(cap10.main_one(NN))
