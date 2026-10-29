"""E42-D04 cap10b board 03 `audit-secret` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  row 1: AL-4 · 1280×800 [04] <- gen/gen_04.py node 'frame-1280' · AL-4 · 2560×1440 [04] <- gen/gen_04.py node 'frame-2560'
  row 2: AD-3 · 1280×800 [32] <- gen/gen_32.py node 'frame-1280' · AD-3 · 2560×1440 [32] <- gen/gen_32.py node 'frame-2560'

Each frame is the old board's frame tree as its generator built it (E42-D04/NN-<slug>.json, read only; harvest.json
records whether the generator still re-runs on its pinned spec and matches; BUILD.md). Writes ../cap10b/03-audit-secret.json
+ .md (validated, exit 0) and packs ../v4/03-audit-secret.json with compact.py.
Usage: python3 -I -B gen10/03-audit-secret.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cap10  # noqa: E402

NN = 3

if __name__ == "__main__":
    raise SystemExit(cap10.main_one(NN))
