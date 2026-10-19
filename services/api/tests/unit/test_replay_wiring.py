"""`replay_wiring` (E26-T02): settings to replay storage ports and read-ahead bounds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from candleviewer import replay_wiring
from candleviewer.app import create_app
from candleviewer.replay.merge import DEFAULT_IO_TIMEOUT_S
from candleviewer.replay.metrics import EXPORTED_NAMES
from candleviewer.replay_wiring import build_replay_wiring, readahead_config
from candleviewer.settings import QUESTDB_PG_DEFAULT_PORT, Environment, Settings
from candleviewer.storage.cold import recorded_reader as cold
from candleviewer.storage.cold.recorded_reader import ParquetRecordedReader
from candleviewer.storage.questdb import recorded_reader as hot
from candleviewer.storage.questdb.recorded_reader import QuestDbRecordedReader
from candleviewer.storage.questdb.wiring import LazyPgWire
from candleviewer.storage.testing import StaticGapReader

MIB, GIB = 1 << 20, 1 << 30


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]  # pydantic-settings kwarg


def test_readahead_bounds_come_from_the_cv_replay_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_REPLAY_READAHEAD_EVENTS", "4096")
    monkeypatch.setenv("CV_REPLAY_READAHEAD_BYTES", str(8 << 20))
    monkeypatch.setenv("CV_REPLAY_MEMORY_CEILING_BYTES", str(32 << 20))

    cfg = readahead_config(_settings())

    assert (cfg.readahead_events, cfg.readahead_bytes, cfg.memory_ceiling_bytes) == (
        4096,
        8 << 20,
        32 << 20,
    )


def test_a_ceiling_not_above_the_readahead_fails_at_startup() -> None:
    with pytest.raises(ValidationError, match="CV_REPLAY_MEMORY_CEILING_BYTES"):
        _settings(replay_readahead_bytes=64 << 20, replay_memory_ceiling_bytes=64 << 20)


@pytest.mark.parametrize(
    ("name", "bound", "past", "others"),
    [
        ("replay_readahead_events", 1_024, 1_023, {}),
        ("replay_readahead_events", 4_194_304, 4_194_305, {}),
        ("replay_readahead_bytes", MIB, MIB - 1, {}),
        ("replay_readahead_bytes", GIB, GIB + 1, {"replay_memory_ceiling_bytes": 4 * GIB}),
        ("replay_memory_ceiling_bytes", 2 * MIB, 2 * MIB - 1, {"replay_readahead_bytes": MIB}),
        ("replay_memory_ceiling_bytes", 4 * GIB, 4 * GIB + 1, {}),
    ],
)
def test_each_readahead_setting_takes_its_bound_and_refuses_one_past_it(
    name: str, bound: int, past: int, others: dict[str, int]
) -> None:
    """C-2.18: no setting removes a read-ahead or memory bound. The other settings are chosen
    so the ceiling still exceeds the read-ahead: only the bound under test can refuse."""
    assert getattr(_settings(**others, **{name: bound}), name) == bound
    with pytest.raises(ValidationError, match=name):  # the field's own bound, not the ceiling check
        _settings(**others, **{name: past})


def test_no_wiring_off_the_real_backend_or_without_a_gap_reader(tmp_path: Path) -> None:
    assert build_replay_wiring(_settings(storage_backend="fake"), StaticGapReader()) is None
    real = _settings(storage_backend="real", parquet_root=str(tmp_path / "parquet"))
    assert build_replay_wiring(real, None) is None


def test_the_real_backend_wires_questdb_parquet_manifest_coverage_and_gaps(
    tmp_path: Path,
) -> None:
    gaps = StaticGapReader()
    settings = _settings(
        storage_backend="real", questdb_pg="questdb:8812", parquet_root=str(tmp_path / "parquet")
    )

    wiring = build_replay_wiring(settings, gaps)

    assert wiring is not None
    tiers = wiring.tiers
    assert isinstance(tiers.hot, QuestDbRecordedReader)
    assert isinstance(tiers.cold, ParquetRecordedReader)
    assert tiers.cold is wiring.cold
    assert tiers.coverage is tiers.cold  # `auto` routes on the cold manifests
    assert tiers.gaps is gaps


@pytest.mark.parametrize(
    ("address", "port"), [("questdb", QUESTDB_PG_DEFAULT_PORT), ("questdb:9009", 9009)]
)
def test_the_questdb_address_names_the_pgwire_port_or_takes_its_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, address: str, port: int
) -> None:
    opened: list[tuple[object, ...]] = []

    def wire(*args: object) -> LazyPgWire:
        opened.append(args[:2])
        return LazyPgWire(*args)  # type: ignore[arg-type]  # the arguments the wiring passes

    monkeypatch.setattr(replay_wiring, "LazyPgWire", wire)
    settings = _settings(
        storage_backend="real", questdb_pg=address, parquet_root=str(tmp_path / "parquet")
    )

    assert build_replay_wiring(settings, StaticGapReader()) is not None
    assert opened == [("questdb", port)]


async def test_aclose_releases_the_questdb_connection_and_the_cold_scan_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    released: list[str] = []

    async def close(self: LazyPgWire) -> None:
        released.append("questdb")

    def shutdown(self: ParquetRecordedReader) -> None:
        released.append("cold")

    monkeypatch.setattr(LazyPgWire, "close", close)
    monkeypatch.setattr(ParquetRecordedReader, "shutdown", shutdown)
    settings = _settings(storage_backend="real", parquet_root=str(tmp_path / "parquet"))
    wiring = build_replay_wiring(settings, StaticGapReader())
    assert wiring is not None

    await wiring.aclose()

    assert released == ["cold", "questdb"]


def test_every_reader_deadline_is_below_the_merge_deadline() -> None:
    """A slow read fails typed in its own tier before the merge's outer timeout cancels it."""
    assert max(hot.DEFAULT_TIMEOUT_S, cold.DEFAULT_TIMEOUT_S) < DEFAULT_IO_TIMEOUT_S


def test_the_app_serves_the_replay_read_path_series_where_prometheus_scrapes() -> None:
    """`create_app` re-exports the replay series on the registry `/metrics` serves, with `env`."""
    settings = _settings(environment=Environment.DEMO, git_sha="deadbeef", version="9.9.9")
    client = TestClient(create_app(settings), client=("127.0.0.1", 50000))

    text = client.get("/metrics").text

    for name in EXPORTED_NAMES:
        assert f"# HELP {name} " in text, name
    assert 'replay_gap_warnings_total{env="demo"}' in text
