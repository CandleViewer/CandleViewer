"""E42-D04 cap10b board 09 `diff-sheet` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  row 1: diff-sheet · 1280×800 [67] <- gen/gen_67.py node 'frame-1280'

Each frame is the old board's frame tree as its generator built it (E42-D04/NN-<slug>.json, read only; harvest.json
records whether the generator still re-runs on its pinned spec and matches; BUILD.md). Writes ../cap10b/09-diff-sheet.json
+ .md (validated, exit 0) and packs ../v4/09-diff-sheet.json with compact.py.
Usage: python3 -I -B gen10/09-diff-sheet.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cap10  # noqa: E402

NN = 9

if __name__ == "__main__":
    raise SystemExit(cap10.main_one(NN))
