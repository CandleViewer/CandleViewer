"""Board 10 `E08-D09 / 10 throttled-hc` (hc): the high-contrast twin of 02 (§0), drawn by gen_02.build("hc") with
02's frames and values. Run: python3 -I -B gen/gen_10.py"""
from __future__ import annotations

import sys
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
for p in (GEN_DIR, GEN_DIR.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import gen_02  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(gen_02.main(10))
