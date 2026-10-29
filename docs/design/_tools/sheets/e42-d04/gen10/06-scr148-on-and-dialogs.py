"""E42-D04 cap10b board 06 `scr148-on-and-dialogs` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  row 1: MM-4 · 1280×800 [57] <- gen/gen_57.py node 'frame-1280' · MM-4 · 2560×1440 [57] <- gen/gen_57.py node 'frame-2560' · MM-5 · 1280×800 [58] <- gen/gen_58.py node 'frame-1280'
  row 2: MM-2 · 1280×800 [55] <- gen/gen_55.py node 'frame-1280' · MM-6 · 1280×800 [59] <- gen/gen_59.py node 'frame-1280'

Each frame is the old board's frame tree as its generator built it (E42-D04/NN-<slug>.json, read only; harvest.json
records whether the generator still re-runs on its pinned spec and matches; BUILD.md). Writes ../cap10b/06-scr148-on-and-dialogs.json
+ .md (validated, exit 0) and packs ../v4/06-scr148-on-and-dialogs.json with compact.py.
Usage: python3 -I -B gen10/06-scr148-on-and-dialogs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cap10  # noqa: E402

NN = 6

if __name__ == "__main__":
    raise SystemExit(cap10.main_one(NN))
