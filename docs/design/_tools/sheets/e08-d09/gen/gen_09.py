"""Board 09 "E08-D09 / 09 clock-light" (§0 L91): the light twin of 05, same frames and values. Run:
python3 -I -B gen_09.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_05 import main  # noqa: E402

if __name__ == "__main__":
    main(9)
