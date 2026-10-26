"""E16 recorder switches: the size floors hold at load, and no request path can reach the
test-only switches (the test clock, the shared-volume hatch). Both stay `Settings` fields that
are read once at startup and refused outside testnet (`test_settings_test_clock.py`,
`test_budget_wiring.py`)."""

from __future__ import annotations

import importlib.util
import pkgutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import candleviewer.api as api_pkg
from candleviewer.settings import Settings


@pytest.mark.parametrize(
    ("field", "below", "floor"),
    [
        ("recorder_max_symbols", 0, 1),
        ("recorder_wal_max_bytes", (1 << 20) - 1, 1 << 20),
        ("disk_cap_gb", 0, 1),
    ],
)
def test_recorder_size_settings_refuse_a_value_below_their_floor(
    field: str, below: int, floor: int
) -> None:
    refused: dict[str, Any] = {field: below}
    accepted: dict[str, Any] = {field: floor}
    with pytest.raises(ValidationError, match=field):
        Settings(**refused)
    assert getattr(Settings(**accepted), field) == floor


def test_no_api_module_reads_the_test_clock_or_the_shared_volume_switch() -> None:
    scanned: list[str] = []
    readers: list[str] = []
    for mod in pkgutil.walk_packages(api_pkg.__path__, f"{api_pkg.__name__}."):
        spec = importlib.util.find_spec(mod.name)
        if spec is None or spec.origin is None or not spec.origin.endswith(".py"):
            continue
        source = Path(spec.origin).read_text(encoding="utf-8")
        scanned.append(mod.name)
        if "test_clock" in source or "allow_shared_volume" in source:
            readers.append(mod.name)
    assert "candleviewer.api.recorder_purge" in scanned and len(scanned) > 20
    assert readers == []
