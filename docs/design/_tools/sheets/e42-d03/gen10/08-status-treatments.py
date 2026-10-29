"""E42-D03 cap10 board 08 `status-treatments` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  status-treatments · dark · 1280×1688 [90] <- gen_90.py node 'frame-1280 · dark' (frame)
  status-treatments · light · 1280×1688 [90] <- gen_90.py node 'frame-1280 · light' (frame)
  status-treatments · hc · 1280×1688 [90] <- gen_90.py node 'frame-1280 · hc' (frame)

Each frame is the old board's frame tree as its generator built it (the recorded source sheet NN-<slug>.json, read
only, from cap10.SOURCES; gen10/harvest.json records that the generator re-ran unchanged and matched; BUILD.md).
Writes cap10/08-status-treatments.json (validated, exit 0; not committed) and 08-status-treatments.md beside the kit, and packs
v4/08-status-treatments.json with ../tools/compact.py.
Usage: python3 -I -B gen10/08-status-treatments.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cap10  # noqa: E402

NN = 8

if __name__ == "__main__":
    raise SystemExit(cap10.main_one(NN))
