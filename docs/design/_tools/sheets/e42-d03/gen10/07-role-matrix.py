"""E42-D03 cap10 board 07 `role-matrix` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  N-6 · Owner (basiltt) · 1280×800 [88] <- gen/gen_88.py node 'role · Owner' (frame)
  N-6 · Manager (alex) · 1280×800 [88] <- gen/gen_88.py node 'role · Manager' (frame)
  N-6 · Viewer (erin) · 1280×800 [88] <- gen/gen_88.py node 'role · Viewer' (frame)

Each frame is the old board's frame tree as its generator built it (E42-D03/NN-<slug>.json, read only; harvest.json
records that the generator re-runs in the sandbox and matches; BUILD.md). Writes ../E42-D03-cap10/07-role-matrix.json + .md
(validated, exit 0) and packs ../E42-D03-cap10-v4/07-role-matrix.json with compact.py.
Usage: python3 -I -B gen10/07-role-matrix.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cap10  # noqa: E402

NN = 7

if __name__ == "__main__":
    raise SystemExit(cap10.main_one(NN))
