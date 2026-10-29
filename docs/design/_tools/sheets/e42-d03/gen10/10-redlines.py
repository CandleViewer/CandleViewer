"""E42-D03 cap10 board 10 `redlines` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  OV-2 redlines · 1280×800 [92] <- gen/gen_92.py node 'frame-1280' (frame)
  OV-2 redlines · 2560×1440 [92] <- gen/gen_92.py node 'frame-2560' (frame)
  legend · spacing and tokens by region (annotation, not a frame) [92] <- gen/gen_92.py node 'legend · spacing and tokens by region (annotation)' (panel, not a frame)
  focus order · stop by stop (annotation, not a frame) [92] <- gen/gen_92.py node 'focus order · stop by stop (annotation)' (panel, not a frame)

Each frame is the old board's frame tree as its generator built it (E42-D03/NN-<slug>.json, read only; harvest.json
records that the generator re-runs in the sandbox and matches; BUILD.md). Writes ../E42-D03-cap10/10-redlines.json + .md
(validated, exit 0) and packs ../E42-D03-cap10-v4/10-redlines.json with compact.py.
Usage: python3 -I -B gen10/10-redlines.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cap10  # noqa: E402

NN = 10

if __name__ == "__main__":
    raise SystemExit(cap10.main_one(NN))
