"""Shared imports for the generators: the kit on sys.path, frame helpers used by several boards."""
from __future__ import annotations

import math
import sys
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e47d05kit as k  # noqa: E402


def full_window(fid: str, ps: "k.PS", *, overlays=(), note: str | None = None) -> tuple[dict, int]:
    """A 1280-wide window holding the whole page (FALLBACKS full-length when it runs past the 800 px viewport)."""
    pg = k.page(ps)
    need = int(math.ceil(k.est_height(pg) / 8) * 8) + 16
    body_h = max(k.BODY_H, need)
    return k.window(k.frame_name(fid), pg, body_h=body_h, overlays=overlays, note=note,
                    nav_focused=ps.focus == "nav"), need


def view_window(fid: str, ps: "k.PS", *, overlays=(), note: str | None = None, settings: bool = True) -> dict:
    """A 1280 x 800 window scrolled so the page's first drawn section sits at the top of main (the rest clips)."""
    return k.window(k.frame_name(fid), k.page(ps), overlays=overlays, note=note, settings=settings)
