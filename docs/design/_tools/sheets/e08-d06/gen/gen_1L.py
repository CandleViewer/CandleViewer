"""Board 1L: board 1's light twin (same frames, same values; token-bound, the theme switches at export)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from a_helpers import emit  # noqa: E402
from gen_1D import build  # noqa: E402

if __name__ == "__main__":
    f, a = build("light")
    emit("1L", f, a, notes={"live_checks": ["board 1L: same nodes as 1D; every fill and text colour is a token "
                                            "binding (nothing painted), so the light set re-binds them at export"]})
