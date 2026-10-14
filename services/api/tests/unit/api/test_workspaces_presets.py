"""Tests for the static layout-presets catalogue (E15-T01 D24)."""

from __future__ import annotations

from candleviewer.api import workspaces_models as wm
from candleviewer.api.workspaces_models import LayoutIn
from candleviewer.api.workspaces_presets import LAYOUT_PRESETS


def test_every_preset_validates_and_matches_its_shape() -> None:
    assert [p.layout.grid_preset for p in LAYOUT_PRESETS] == [
        "1x1", "2x1", "1x2", "2x2", "1+3", "3x3",
    ]  # fmt: skip
    for p in LAYOUT_PRESETS:
        again = LayoutIn.model_validate(p.layout.model_dump(mode="json"))
        assert again == p.layout
        assert p.pane_count == len(p.layout.panes) <= wm.MAX_PANES
        assert p.is_builtin and p.layout.grid_spec is None


def test_preset_ids_are_unique_and_fixed() -> None:
    ids = [str(p.id) for p in LAYOUT_PRESETS]
    assert ids == [f"15000000-0000-4000-8000-00000000020{n}" for n in range(1, 7)]
