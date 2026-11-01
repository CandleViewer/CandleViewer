"""E47-D04 / 09 ring-spec-light: the light twin of 08 (same frames; the light token set at export)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_08 import build  # noqa: E402

if __name__ == "__main__":
    build("light")
