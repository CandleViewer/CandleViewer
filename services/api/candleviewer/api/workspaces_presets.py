"""Static layout-presets catalogue for ``GET /layout-presets`` (E15-T01, D24).

WHY static code: the catalogue has no per-user rows; ids are fixed constants so clients can
cache and link them. Workflow presets (Scalping, Order-flow, ...) are E15-S01's and are added
additively. Every entry is a validated `LayoutIn`, so a bad edit fails at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from candleviewer.api.workspaces_models import LayoutGridPreset, LayoutIn


@dataclass(frozen=True, slots=True)
class LayoutPresetEntry:
    id: UUID
    name: str
    description: str
    pane_count: int
    layout: LayoutIn
    is_builtin: bool = True


def _entry(n: int, preset: LayoutGridPreset, cells: int, description: str) -> LayoutPresetEntry:
    layout = LayoutIn.model_validate(
        {
            "name": preset,
            "grid_preset": preset,
            "panes": [{"slot_index": i, "pane_kind": "chart"} for i in range(cells)],
        }
    )
    return LayoutPresetEntry(
        UUID(f"15000000-0000-4000-8000-00000000020{n}"), preset, description, cells, layout
    )


LAYOUT_PRESETS: Final[tuple[LayoutPresetEntry, ...]] = (
    _entry(1, "1x1", 1, "One chart."),
    _entry(2, "2x1", 2, "Two charts side by side."),
    _entry(3, "1x2", 2, "Two charts stacked."),
    _entry(4, "2x2", 4, "Four charts in a grid."),
    _entry(5, "1+3", 4, "One large chart and three small ones."),
    _entry(6, "3x3", 9, "Nine charts in a grid."),
)
