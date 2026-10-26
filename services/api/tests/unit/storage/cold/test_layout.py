"""Unit tests: `DatasetRegistry` path resolution and traversal safety
(SR-097). See ticket AC: "a query() call with dataset_id='../../etc/passwd'
or a symlinked partition directory ... the registry rejects it"."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from candleviewer.storage.cold.layout import DatasetNotRegistered, DatasetRegistry
from candleviewer.storage.models import StreamKind


def test_resolve_partition_trades_builds_expected_path(tmp_path: Path) -> None:
    registry = DatasetRegistry(tmp_path)
    paths = registry.resolve_partition(
        StreamKind.TRADES, partition_values={"symbol": "BTCUSDT", "dt": "2026-10-17"}
    )
    assert paths.partition_dir == tmp_path / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17"
    assert paths.manifests_dir == tmp_path / "_manifests"
    assert paths.schema_registry_path == tmp_path / "_manifests" / "schema-registry.json"


def test_resolve_partition_unregistered_stream_raises(tmp_path: Path) -> None:
    registry = DatasetRegistry(tmp_path)
    with pytest.raises(DatasetNotRegistered):
        registry.resolve_partition("not-a-stream", partition_values={})  # type: ignore[arg-type]


def test_resolve_partition_missing_key_raises(tmp_path: Path) -> None:
    registry = DatasetRegistry(tmp_path)
    with pytest.raises(DatasetNotRegistered):
        registry.resolve_partition(StreamKind.TRADES, partition_values={"symbol": "BTCUSDT"})


@pytest.mark.parametrize(
    "value",
    ["../../etc/passwd", "..", ".", "a/b", "a\\b", "", "a b"],
)
def test_resolve_partition_rejects_traversal_values(tmp_path: Path, value: str) -> None:
    registry = DatasetRegistry(tmp_path)
    with pytest.raises(DatasetNotRegistered):
        registry.resolve_partition(
            StreamKind.TRADES, partition_values={"symbol": value, "dt": "2026-10-17"}
        )


_HOSTILE = [
    "../x",
    "/abs",
    "C:\\x",
    "\\\\srv\\share",
    "x\x00y",
    ".hidden",
    "x;rm",
    "%2e%2e",
]


@pytest.mark.parametrize("key", ["symbol", "dt"])
@pytest.mark.parametrize("value", _HOSTILE)
def test_resolve_partition_rejects_hostile_values_in_every_key(
    tmp_path: Path, key: str, value: str
) -> None:
    """Every partition key is a closed charset: no separator, drive, UNC root, NUL, dotfile,
    shell metacharacter or percent-encoding reaches a path, whichever key carries it."""
    registry = DatasetRegistry(tmp_path)
    values = {"symbol": "BTCUSDT", "dt": "2026-10-17"} | {key: value}
    with pytest.raises(DatasetNotRegistered):
        registry.resolve_partition(StreamKind.TRADES, partition_values=values)
    assert list(tmp_path.iterdir()) == []


def test_resolve_partition_rejects_absolute_value(tmp_path: Path) -> None:
    registry = DatasetRegistry(tmp_path)
    absolute = str(tmp_path.parent)
    with pytest.raises(DatasetNotRegistered):
        registry.resolve_partition(
            StreamKind.TRADES, partition_values={"symbol": absolute, "dt": "2026-10-17"}
        )


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin/dev-mode on Windows CI")
def test_resolve_partition_rejects_symlinked_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-escape-target"
    outside.mkdir(exist_ok=True)
    root = tmp_path / "cold"
    root.mkdir()
    trades_dir = root / "trades"
    trades_dir.mkdir()
    symlinked_symbol = trades_dir / "symbol=BTCUSDT"
    os.symlink(outside, symlinked_symbol, target_is_directory=True)

    registry = DatasetRegistry(root)
    with pytest.raises(DatasetNotRegistered):
        registry.resolve_partition(
            StreamKind.TRADES, partition_values={"symbol": "BTCUSDT", "dt": "2026-10-17"}
        )


def test_dataset_glob_matches_partition_depth(tmp_path: Path) -> None:
    registry = DatasetRegistry(tmp_path)
    glob = registry.dataset_glob(StreamKind.TRADES)
    assert glob == str(tmp_path / "trades" / "*" / "*" / "*.parquet")


def test_ensure_tree_creates_root_and_manifests(tmp_path: Path) -> None:
    root = tmp_path / "cold"
    registry = DatasetRegistry(root)
    registry.ensure_tree()
    assert root.is_dir()
    assert (root / "_manifests").is_dir()


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS junction variant of the symlink test")
def test_resolve_partition_rejects_junction_escape_on_windows(tmp_path: Path) -> None:
    import _winapi  # type: ignore[import-not-found,unused-ignore]  # Windows-only stdlib module

    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "cold"
    (root / "trades").mkdir(parents=True)
    _winapi.CreateJunction(str(outside), str(root / "trades" / "symbol=BTCUSDT"))
    with pytest.raises(DatasetNotRegistered):
        DatasetRegistry(root).resolve_partition(
            StreamKind.TRADES, partition_values={"symbol": "BTCUSDT", "dt": "2026-10-17"}
        )


def test_manifested_partitions_discovers_only_registered_shapes(tmp_path: Path) -> None:
    registry = DatasetRegistry(tmp_path)
    base = tmp_path / "_manifests" / "trades"
    for rel in (
        "symbol=BTCUSDT/dt=2026-10-17.json",
        "symbol=BTCUSDT/dt=2026-10-18.json",
        "symbol=ETHUSDT/dt=2026-10-17.json",
        "symbol=BTCUSDT/junk.json",
        "symbol=BTCUSDT/dt=..%2F.json",
    ):
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_text("{}", encoding="utf-8")
    found = registry.manifested_partitions(StreamKind.TRADES, "BTCUSDT")
    assert [p.partition_dir.name for p in found] == ["dt=2026-10-17", "dt=2026-10-18"]
    assert registry.manifested_partitions(StreamKind.BARS, "BTCUSDT") == []


def test_partition_template_unregistered_raises() -> None:
    from candleviewer.storage.cold.layout import partition_template

    assert partition_template(StreamKind.TRADES) == ("symbol", "dt")
    with pytest.raises(DatasetNotRegistered):
        partition_template("nope")  # type: ignore[arg-type]  # deliberately unregistered id
