"""The recorder chaos rig's volume (E16-Q04, C-13.6 #13): real files under `tmp_path`, faked size.

`VirtualVolume` is a recording volume of `total` bytes rooted in a pytest tmp dir. Its free space
is `total` less the bytes of every file under it, so filling it is writing real files and
reclaiming it is deleting them: the ladder reads exactly what retention frees. No mount, no root,
no loopback image (the brief's `_loopback.py` needs sudo; see SCENARIOS.md "Deviations"), and it
refuses any root outside the tmp dir it was given, so a mistaken path can never fill a real disk.

`VolumeMeter` is the `StorageMeter` `DiskBudget` samples; `VolumeRetention` is every port the
E07 `Reaper` takes, over the same files. The volume is the whole cap (`cap == total`), so the
used share the budget's ladder reads and the free share the reaper reads always add to 100 %:
81 % used is 19 % free, 91 % is 9 % (the reaper accelerates below 15) and 96 % is 4 % (it pauses
below 5).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from candleviewer.recorder.budget import Breakdown
from candleviewer.recorder.models import TierName
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.retention.ports import Partition, Tier

#: The volume's size: 1 MB, a multiple of 100 so every whole-percent fill is exact (the events
#: report integer percentages). The smoke scale; the ladder works in shares, not bytes.
TOTAL: Final = 1_000_000
PART_BYTES: Final = 4096
NOW: Final = datetime(2026, 10, 20, 2, 15, tzinfo=UTC)
NOW_US: Final = int(NOW.timestamp() * 1_000_000)
DAY_US: Final = 86_400_000_000
_TIER_DIR: Final[dict[Tier, TierName]] = {"hot": "questdb", "cold": "parquet"}
_FILL: Final = Path("questdb") / "_fill" / "fill.bin"


class VirtualVolume:
    """A volume of `total` bytes whose used bytes are the files under `root` (see module)."""

    def __init__(self, root: Path, total: int, *, tmp_root: Path) -> None:
        base, target = tmp_root.resolve(), root.resolve()
        if target == base or not target.is_relative_to(base):
            raise RuntimeError(f"chaos volume {root} is not inside the test's tmp dir {tmp_root}")
        self.root, self.total = target, total
        self.root.mkdir(parents=True, exist_ok=True)

    def _files(self) -> list[Path]:
        return sorted(p for p in self.root.rglob("*") if p.is_file())

    def used(self) -> int:
        return sum(p.stat().st_size for p in self._files())

    def free(self) -> int:
        return max(0, self.total - self.used())

    def free_pct(self) -> float:
        return self.free() * 100 / self.total

    def fill_to(self, pct: int) -> None:
        """Size the one filler file so the volume is `pct` % used (whole bytes, rounded down)."""
        fill = self.root / _FILL
        current = fill.stat().st_size if fill.exists() else 0
        size = self.total * pct // 100 - (self.used() - current)
        if size < 0:
            raise ValueError(f"the volume already holds more than {pct} %")
        fill.parent.mkdir(parents=True, exist_ok=True)
        with fill.open("wb") as f:
            f.truncate(0)
            f.write(b"\0" * size)

    def part_path(self, symbol: str, tier: Tier, age_days: int) -> Path:
        return self.root / _TIER_DIR[tier] / f"symbol={symbol}" / "trades" / f"{age_days}.bin"

    def add_partition(self, symbol: str, tier: Tier, age_days: int) -> Path:
        """One day of trades, `age_days` old: `PART_BYTES` of deterministic content."""
        path = self.part_path(symbol, tier, age_days)
        path.parent.mkdir(parents=True, exist_ok=True)
        seed = f"{symbol}:{tier}:{age_days}".encode()
        path.write_bytes((hashlib.sha256(seed).digest() * (PART_BYTES // 32))[:PART_BYTES])
        return path

    def digest(self, symbol: str) -> str:
        """sha256 over every partition file of `symbol` (path and bytes), in path order."""
        h = hashlib.sha256()
        for p in self._files():
            if f"symbol={symbol}" in p.parts:
                h.update(p.relative_to(self.root).as_posix().encode())
                h.update(p.read_bytes())
        return h.hexdigest()

    def symbol_bytes(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in self._files():
            for part in p.parts:
                if part.startswith("symbol="):
                    sym = part.removeprefix("symbol=")
                    out[sym] = out.get(sym, 0) + p.stat().st_size
        return out

    def tier_bytes(self, tier: TierName) -> int:
        base = self.root / tier
        return sum(p.stat().st_size for p in base.rglob("*") if p.is_file()) if base.exists() else 0


class VolumeMeter:
    """`StorageMeter` over a `VirtualVolume` (the free-space path first, then the breakdown)."""

    def __init__(self, vol: VirtualVolume) -> None:
        self.vol = vol

    async def volume(self) -> tuple[int, int]:
        return self.vol.total, self.vol.free()

    async def breakdown(self) -> Breakdown:
        tiers: dict[TierName, int] = {"questdb": self.vol.tier_bytes("questdb")}
        tiers["parquet"] = self.vol.tier_bytes("parquet")
        return Breakdown(tiers, self.vol.symbol_bytes())

    async def close(self) -> None:
        return None


class VolumeRetention:
    """Every `Reaper` port over a `VirtualVolume`: partitions are its files, a drop deletes one.
    Pins, auto-recorded symbols, audits, events and pauses are recorded in `log` in call order."""

    def __init__(self, volume: VirtualVolume, *, pinned: set[str], auto: set[str]) -> None:
        self.volume, self.pinned, self.auto = volume, pinned, auto
        self.log: list[str] = []
        self.audits: list[tuple[str, dict[str, str | int]]] = []
        self.events: list[tuple[str, str, dict[str, str | int]]] = []
        self.paused: list[str] = []

    def _parts(self, tier: Tier) -> list[tuple[Path, Partition]]:
        base = self.volume.root / _TIER_DIR[tier]
        out = []
        for path in sorted(base.glob("symbol=*/trades/*.bin")) if base.exists() else []:
            symbol = path.parent.parent.name.removeprefix("symbol=")
            end = NOW_US - int(path.stem) * DAY_US
            rng = TimeRange(start_us=end - DAY_US, end_us=end)
            size = path.stat().st_size
            out.append((path, Partition(symbol, StreamKind.TRADES, tier, rng, 100, size)))
        return out

    async def list_partitions(self, symbol: str, stream: StreamKind, tier: Tier) -> list[Partition]:
        return [p for _, p in self._parts(tier) if p.symbol == symbol and p.stream == stream]

    async def is_exported_and_verified(self, part: Partition) -> bool:
        return True

    async def drop(self, part: Partition) -> None:
        for path, p in self._parts(part.tier):
            if p == part:
                path.unlink()
                self.log.append(f"drop:{p.symbol}:{p.tier}")

    async def symbols(self) -> list[str]:
        return sorted({p.symbol for t in _TIER_DIR for _, p in self._parts(t)})

    async def pinned_symbols(self) -> set[str]:
        return set(self.pinned)

    async def priority(self, symbol: str) -> int:
        return 0

    async def auto_recorded_symbols(self) -> set[str]:
        return set(self.auto)

    async def replay_session_for(self, part: Partition) -> str | None:
        return None

    async def has_unexported_journal_trade(self, part: Partition) -> bool:
        return False

    def free_pct(self) -> float:
        return self.volume.free_pct()

    async def write(self, action: str, detail: dict[str, str | int]) -> None:
        self.audits.append((action, detail))
        self.log.append(f"audit:{action}")

    async def emit(self, severity: str, code: str, detail: dict[str, str | int]) -> None:
        self.events.append((severity, code, detail))
        self.log.append(f"event:{severity}:{code}")

    async def pause(self, symbol: str) -> None:
        self.paused.append(symbol)
        self.log.append(f"pause:{symbol}")
