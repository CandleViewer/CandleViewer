"""E42-D03 cap10 board 01 `tint-proof` (dark+light): the confirmed plan's frames, composed by gen10/cap10.py.

  OV-2 · SCR-120 overview · 1280×800 [09] <- gen/gen_09.py node 'frame-1280 SCR-120 overview' (frame)
  SCR-010 · workspace · 1280×800 [09] <- gen/gen_09.py node 'frame-1280 SCR-010 workspace' (frame)

Each frame is the old board's frame tree as its generator built it (E42-D03/NN-<slug>.json, read only; harvest.json
records that the generator re-runs in the sandbox and matches; BUILD.md). Writes ../E42-D03-cap10/01-tint-proof.json + .md
(validated, exit 0) and packs ../E42-D03-cap10-v4/01-tint-proof.json with compact.py.
Usage: python3 -I -B gen10/01-tint-proof.py
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
