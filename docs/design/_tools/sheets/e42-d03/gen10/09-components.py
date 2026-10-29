"""E42-D03 cap10 board 09 `components` (dark): the confirmed plan's frames, composed by gen10/cap10.py.

  components · CMP-087 stories · 1280×800 [91] <- gen/gen_91.py node 'frame-1280' (frame)
  components · sheet page 2, the other contracts' stories (DEV panel, not a frame) [91] <- gen/gen_91.py node 'frame-2560' (panel, not a frame)
  components · SCR-121 parts at 1280 (DEV panel, not a frame) [91] <- gen/gen_91.py node 'panel · SCR-121 parts at 1280 (not a frame)' (panel, not a frame)

Each frame is the old board's frame tree as its generator built it (E42-D03/NN-<slug>.json, read only; harvest.json
records that the generator re-runs in the sandbox and matches; BUILD.md). Writes ../E42-D03-cap10/09-components.json + .md
(validated, exit 0) and packs ../E42-D03-cap10-v4/09-components.json with compact.py.
Usage: python3 -I -B gen10/09-components.py
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
