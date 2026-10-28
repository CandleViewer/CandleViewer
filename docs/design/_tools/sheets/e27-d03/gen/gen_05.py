"""E27-D03 / 05 scr-125-128-accounts-light: the light twin of board 04 (§0 L222; build notes §1 step 2).

Run:  python3 -I -B docs/design/_tools/sheets/e27-d03/gen/gen_05.py
Draws board 04's 20 frames again with gen_04.build_cells() — the same names, the same token names; semantic-light is
applied through the file's light theme at export (kit choice `light`; HD13). Writes 05-scr-125-128-accounts-light.json
(validated), its compacted twin in v4/ (compactOf sha guard) and the .md (line 3 says "theme light.").
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_04

k = gen_04.k
NN = 5

if __name__ == "__main__":
    if k.BOARDS[NN].twin_of != gen_04.NN:
        raise SystemExit(
            f"board 05 is not the twin of board 04 in the kit ({k.BOARDS[NN].twin_of})"
        )
    gen_04.emit(NN, gen_04.build_cells())
