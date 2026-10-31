"""The recorder chaos rig's own guards (E16-Q04): the volume never leaves `tmp_path`, fills to the
share it is asked for, and the meter reads it as `DiskBudget` and the reaper expect."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.chaos.recorder._ladder import PINNED, LadderRig
from tests.chaos.recorder._volume import PART_BYTES, TOTAL, VirtualVolume, VolumeMeter

pytestmark = pytest.mark.chaos


@pytest.mark.parametrize("outside", ["/var/lib/candleviewer", "../escape"])
def test_volume_refuses_a_root_outside_the_tmp_dir(tmp_path: Path, outside: str) -> None:
    with pytest.raises(RuntimeError, match="not inside the test's tmp dir"):
        VirtualVolume(tmp_path / outside, TOTAL, tmp_root=tmp_path)  # an absolute one replaces


def test_volume_refuses_the_tmp_dir_itself(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="not inside"):
        VirtualVolume(tmp_path, TOTAL, tmp_root=tmp_path)


def test_fill_to_reaches_the_share_and_refuses_an_overfull_volume(tmp_path: Path) -> None:
    v = VirtualVolume(tmp_path / "rec", TOTAL, tmp_root=tmp_path)
    v.add_partition("BTCUSDT", "hot", 3)
    for pct in (96, 76, 91):  # shrinking refills too
        v.fill_to(pct)
        assert v.used() == TOTAL * pct // 100
    small = VirtualVolume(tmp_path / "small", PART_BYTES * 2, tmp_root=tmp_path)
    small.add_partition("BTCUSDT", "hot", 3)
    with pytest.raises(ValueError, match="more than 10 %"):
        small.fill_to(10)


async def test_meter_reads_free_space_and_the_tier_and_symbol_breakdown(tmp_path: Path) -> None:
    v = VirtualVolume(tmp_path / "rec", TOTAL, tmp_root=tmp_path)
    v.add_partition("BTCUSDT", "hot", 3)
    v.add_partition("ETHUSDT", "cold", 40)
    v.fill_to(50)
    meter = VolumeMeter(v)
    assert await meter.volume() == (TOTAL, TOTAL - TOTAL // 2)
    b = await meter.breakdown()
    assert b.tiers["parquet"] == PART_BYTES and b.tiers["questdb"] == TOTAL // 2 - PART_BYTES
    assert dict(b.symbols) == {"BTCUSDT": PART_BYTES, "ETHUSDT": PART_BYTES}


async def test_rig_keeps_the_wal_off_the_recording_volume(
    ladder: LadderRig, tmp_path: Path
) -> None:
    """SR-096: the spill WAL never shares the volume it would protect."""
    wal = tmp_path / "wal"
    assert wal.is_dir() and not wal.resolve().is_relative_to(ladder.volume.root)
    assert ladder.volume.digest(PINNED) == ladder.pinned_digest
