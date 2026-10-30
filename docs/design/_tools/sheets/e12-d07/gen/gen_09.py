"""Board 09 `E12-D07 / 09 row-states-light`: the light twin of 04's states/all-words (same builder, light fid).
Run: python3 -I gen_09.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_04  # noqa: E402

if __name__ == "__main__":
    for p in gen_04.build(9):
        print(p)
