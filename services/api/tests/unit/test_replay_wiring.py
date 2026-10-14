"""`replay_wiring` (E26-T02): settings to replay storage ports and read-ahead bounds."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from candleviewer.replay.merge import DEFAULT_IO_TIMEOUT_S
from candleviewer.replay_wiring import build_replay_tiers, readahead_config
from candleviewer.settings import Settings
from candleviewer.storage.cold import recorded_reader as cold
from candleviewer.storage.cold.recorded_reader import ParquetRecordedReader
from candleviewer.storage.questdb import recorded_reader as hot
from candleviewer.storage.questdb.recorded_reader import QuestDbRecordedReader
from candleviewer.storage.testing import StaticGapReader


def test_readahead_bounds_come_from_the_cv_replay_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_REPLAY_READAHEAD_EVENTS", "4096")
    monkeypatch.setenv("CV_REPLAY_READAHEAD_BYTES", str(8 << 20))
    monkeypatch.setenv("CV_REPLAY_MEMORY_CEILING_BYTES", str(32 << 20))

    cfg = readahead_config(Settings())

    assert (cfg.readahead_events, cfg.readahead_bytes, cfg.memory_ceiling_bytes) == (
        4096,
        8 << 20,
        32 << 20,
    )


def test_a_ceiling_not_above_the_readahead_fails_at_startup() -> None:
    with pytest.raises(ValidationError, match="CV_REPLAY_MEMORY_CEILING_BYTES"):
        Settings(replay_readahead_bytes=64 << 20, replay_memory_ceiling_bytes=64 << 20)


def test_no_tiers_off_the_real_backend_or_without_a_gap_reader(tmp_path: Path) -> None:
    assert build_replay_tiers(Settings(storage_backend="fake"), StaticGapReader()) is None
    real = Settings(storage_backend="real", parquet_root=str(tmp_path / "parquet"))
    assert build_replay_tiers(real, None) is None


def test_the_real_backend_wires_questdb_parquet_manifest_coverage_and_gaps(
    tmp_path: Path,
) -> None:
    gaps = StaticGapReader()
    settings = Settings(
        storage_backend="real", questdb_pg="questdb:8812", parquet_root=str(tmp_path / "parquet")
    )

    tiers = build_replay_tiers(settings, gaps)

    assert tiers is not None
    assert isinstance(tiers.hot, QuestDbRecordedReader)
    assert isinstance(tiers.cold, ParquetRecordedReader)
    assert tiers.coverage is tiers.cold  # `auto` routes on the cold manifests
    assert tiers.gaps is gaps


def test_every_reader_deadline_is_below_the_merge_deadline() -> None:
    """A slow read fails typed in its own tier before the merge's outer timeout cancels it."""
    assert max(hot.DEFAULT_TIMEOUT_S, cold.DEFAULT_TIMEOUT_S) < DEFAULT_IO_TIMEOUT_S
