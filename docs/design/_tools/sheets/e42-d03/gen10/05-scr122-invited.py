"""E42-D03 cap10 board 05 `scr122-invited` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  UD-16 · 1280×800 [57] <- gen/gen_57.py node 'frame-1280' (frame)
  UD-16 · 2560×1440 [57] <- gen/gen_57.py node 'frame-2560' (frame)

Each frame is the old board's frame tree as its generator built it (E42-D03/NN-<slug>.json, read only; harvest.json
records that the generator re-runs in the sandbox and matches; BUILD.md). Writes ../E42-D03-cap10/05-scr122-invited.json + .md
(validated, exit 0) and packs ../E42-D03-cap10-v4/05-scr122-invited.json with compact.py.
Usage: python3 -I -B gen10/05-scr122-invited.py
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
