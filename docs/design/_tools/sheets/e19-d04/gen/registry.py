"""The frame registry: §0 frame id -> builder(theme) -> (frame node, annotation lines); build_board(nn)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e19d04kit as k  # noqa: E402
import flows as F  # noqa: E402

Builder = Callable[[str], tuple[k.Node, list[str]]]
_BY_STEM: dict[str, Callable[[str], tuple[k.Node, list[str]]]] = {
    "preset-menu": F.f_preset_menu, "preset-menu-empty": F.f_preset_empty, "preset-modified": F.f_preset_modified,
    "preset-save": F.f_preset_save, "preset-conflict": F.f_preset_conflict, "preset-rename": F.f_preset_rename,
    "preset-delete": F.f_preset_delete, "preset-applied": F.f_preset_applied, "preset-restored": F.f_preset_restored,
    "range-mode": F.f_range_mode, "range-handles": F.f_range_handles, "anchored": F.f_anchored,
    "anchor-removed": F.f_anchor_removed, "attach-menu": F.f_attach_menu, "attached": F.f_attached,
    "drawing-moved": F.f_drawing_moved, "drawing-locked": F.f_drawing_locked, "drawing-hidden": F.f_drawing_hidden,
    "drawing-deleted": F.f_drawing_deleted, "drawing-shared": F.f_drawing_shared, "gesture-matrix": F.f_matrix,
    "range-keyboard": F.f_range_keyboard, "attach-keyboard": F.f_attach_keyboard, "visible-pan": F.f_visible_pan,
    "visible-stale": F.f_visible_stale, "preset-view-as": F.f_preset_view_as,
}


def _stem(fid: str) -> str:
    return fid.split("/", 1)[1].rsplit("-", 1)[0]


BUILDERS: dict[str, Builder] = {f: (lambda th, f=f: _BY_STEM[_stem(f)](f)) for b in k.BOARDS.values()
                                for f in b.frames}


def build_board(nn: int, *, board_lines: tuple[str, ...] = ()) -> tuple[Path, Path, Path]:
    b = k.BOARDS[nn]
    k.NOTES.reset()
    nodes, blocks = [], []
    for fid in b.frames:
        th = k.frame_theme(fid, b.theme)
        n, lines = BUILDERS[fid](th)
        nodes.append(n)
        blocks.append(k.frame_block(fid, th, lines))
    return k.build(nn, nodes, blocks, board_lines=board_lines)
