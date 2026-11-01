"""Board 04 (§0, §H): every frame from gen/frames.py by its §H id. Run: python3 -I -B gen/gen_04.py"""
from __future__ import annotations

import sys
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
for p in (GEN_DIR, GEN_DIR.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import frames  # noqa: E402

if __name__ == "__main__":
    sheet, md, packed = frames.build_board(4)
    print(sheet.name, md.name, packed.name)
