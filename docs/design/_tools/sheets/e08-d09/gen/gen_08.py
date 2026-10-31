"""Board 08 `E08-D09 / 08 healthy-light` (§0: light twin of 01): board 01's frames and values, light theme.
Run: python3 -I -B gen_08.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_01  # noqa: E402

NN = 8

if __name__ == "__main__":
    gen_01.main(NN)
