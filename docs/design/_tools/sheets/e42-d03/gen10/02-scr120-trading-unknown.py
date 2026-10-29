"""E42-D03 cap10 board 02 `scr120-trading-unknown` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  OV-6 · 1280×800 [26] <- gen_26.py node 'frame-1280' (frame)
  OV-6 · 2560×1440 [26] <- gen_26.py node 'frame-2560' (frame)

Each frame is the old board's frame tree as its generator built it (the recorded source sheet NN-<slug>.json, read
only, from cap10.SOURCES; gen10/harvest.json records that the generator re-ran unchanged and matched; BUILD.md).
Writes cap10/02-scr120-trading-unknown.json (validated, exit 0; not committed) and 02-scr120-trading-unknown.md beside the kit, and packs
v4/02-scr120-trading-unknown.json with ../tools/compact.py.
Usage: python3 -I -B gen10/02-scr120-trading-unknown.py
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
