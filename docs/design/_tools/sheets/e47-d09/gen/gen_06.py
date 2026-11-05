"""E47-D09 / 06 palette-light: the light twin of board 05 (same frames, token-bound; the theme is set at export)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_05  # noqa: E402

if __name__ == "__main__":
    gen_05.build("light")
