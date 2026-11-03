"""The frame registry: §0 frame id -> builder() -> (frame node, annotation lines); build_board(nn)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e19d02kit as k  # noqa: E402
import frames as F  # noqa: E402

Builder = Callable[[], tuple[k.Node, list[str]]]
BUILDERS: dict[str, Builder] = {
    "SCR-038/docked-compact": lambda: F.f_docked("SCR-038/docked-compact", "compact"),
    "SCR-038/docked-dense": lambda: F.f_docked("SCR-038/docked-dense", "dense"),
    "SCR-038/docked-comfortable": lambda: F.f_docked("SCR-038/docked-comfortable", "comfortable"),
    "SCR-038/degraded": lambda: F.f_degraded("SCR-038/degraded"),
    "SCR-038/overlay-compact": lambda: F.f_overlay("SCR-038/overlay-compact", "compact", "volume"),
    "SCR-038/overlay-dense": lambda: F.f_overlay("SCR-038/overlay-dense", "dense", "delta"),
    "SCR-038/overlay-comfortable": lambda: F.f_overlay("SCR-038/overlay-comfortable", "comfortable", "tpo"),
    "SCR-038/aligned-linear": lambda: F.f_aligned_linear("SCR-038/aligned-linear"),
    "SCR-038/aligned-log": lambda: F.f_aligned_log("SCR-038/aligned-log"),
    "SCR-038/aligned-mid-fit": lambda: F.f_aligned_mid_fit("SCR-038/aligned-mid-fit"),
    "SCR-038/not-aligned": lambda: F.f_not_aligned("SCR-038/not-aligned"),
    "SCR-038/loading": lambda: F.f_loading("SCR-038/loading"),
    "SCR-038/partial": lambda: F.f_partial("SCR-038/partial"),
    "SCR-038/approximated": lambda: F.f_approximated("SCR-038/approximated"),
    "SCR-038/developing": lambda: F.f_developing("SCR-038/developing"),
    "SCR-038/final": lambda: F.f_final("SCR-038/final"),
    "SCR-038/no-history-owner": lambda: F.f_no_history("SCR-038/no-history-owner", "owner"),
    "SCR-038/no-history-sentence": lambda: F.f_no_history("SCR-038/no-history-sentence", "sentence"),
    "SCR-038/no-history-view-as": lambda: F.f_no_history("SCR-038/no-history-view-as", "view-as"),
    "SCR-038/edge-5000-rows": lambda: F.f_edge5000("SCR-038/edge-5000-rows"),
    "SCR-038/edge-two-level": lambda: F.f_edge_two_level("SCR-038/edge-two-level"),
    "SCR-038/edge-composite-30": lambda: F.f_edge_composite("SCR-038/edge-composite-30"),
    "SCR-038/edge-va-spans-view": lambda: F.f_va_spans("SCR-038/edge-va-spans-view"),
    "SCR-038/table": lambda: F.f_table("SCR-038/table"),
    "SCR-039/compact": lambda: F.f_settings_compact("SCR-039/compact"),
    "SCR-039/va-invalid": lambda: F.f_va_invalid("SCR-039/va-invalid"),
    "SCR-039/end-before-start": lambda: F.f_end_before_start("SCR-039/end-before-start"),
    "SCR-039/lookback-warning": lambda: F.f_lookback("SCR-039/lookback-warning"),
    "SCR-038/presets-entry": lambda: F.f_presets_entry("SCR-038/presets-entry"),
    "SCR-038/presets-view-as": lambda: F.f_presets_view_as("SCR-038/presets-view-as"),
    "SCR-039/row-size-clamped": lambda: F.f_row_clamped("SCR-039/row-size-clamped"),
    "SCR-039/view-as": lambda: F.f_settings_view_as("SCR-039/view-as"),
    "SCR-038/period-menu": lambda: F.f_period_menu("SCR-038/period-menu"),
    "SCR-038/fixed-range-drag": lambda: F.f_fixed_range("SCR-038/fixed-range-drag"),
    "SCR-038/anchored-place": lambda: F.f_anchored("SCR-038/anchored-place"),
}
BOARD_LINES: dict[int, tuple[str, ...]] = {
    5: ("T2 (§1.4): the no-history CTA for a Manager or Viewer and under view-as is the sentence form (CMP-026 with "
        "cta omitted): the reason as a sentence, no button, no glyph",),
    9: ("T2 (§1.4, E09-D09 §2.1): every gated control keeps its role and full label, the CMP-019 lock leading, the "
        "label in color.text.tertiary on the raised fill with the default hairline, aria-disabled (never disabled, "
        "never opacity.disabled), the reason visible and linked by aria-describedby",),
}


def build_board(nn: int) -> tuple[Path, Path, Path]:
    b = k.BOARDS[nn]
    k.NOTES.reset()
    nodes, blocks = [], []
    for fid in b.frames:
        n, lines = BUILDERS[fid]()
        nodes.append(n)
        blocks.append(k.frame_block(fid, lines))
    return k.build(nn, nodes, blocks, board_lines=BOARD_LINES.get(nn, ()))
