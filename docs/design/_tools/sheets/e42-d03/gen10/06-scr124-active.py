"""E42-D03 cap10 board 06 `scr124-active` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  V-4 · 1280×800 [72] <- gen/gen_72.py node 'frame-1280' (frame)
  V-4 · 2560×1440 [72] <- gen/gen_72.py node 'frame-2560' (frame)
  V-4 insets · under V-4 · 1280×800 (not frames) [72] <- gen/gen_72.py node 'insets · under frame-1280 (not frames)' (panel, not a frame)

Each frame is the old board's frame tree as its generator built it (E42-D03/NN-<slug>.json, read only; harvest.json
records that the generator re-runs in the sandbox and matches; BUILD.md). Writes ../E42-D03-cap10/06-scr124-active.json + .md
(validated, exit 0) and packs ../E42-D03-cap10-v4/06-scr124-active.json with compact.py.
Usage: python3 -I -B gen10/06-scr124-active.py
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
