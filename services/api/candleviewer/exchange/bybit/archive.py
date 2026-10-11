"""Bybit public trade-archive adapter (E16-T10) - implements `TradeArchiveSource`.

All Bybit archive knowledge lives here (C-2.2):

* **URL scheme.** `<base>/trading/<SYMBOL>/<SYMBOL><YYYY-MM-DD>.csv.gz`, base configurable
  (`CV_BYBIT_ARCHIVE_BASE`) but host-pinned to `ALLOWED_ARCHIVE_HOSTS`, https only, no
  redirects followed (E16-FR-02). File names are built from a validated symbol and an ISO date,
  never from server-supplied names or listings (SR-097).
* **CSV schema** (header row required, exact column set, order-independent):
  `timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,
  foreignNotional`. `timestamp` is epoch seconds with a fractional part (decimal string),
  `side` is `Buy`/`Sell` (taker side), `trdMatchID` is the trade id.
* **Integrity.** Bybit publishes no per-file checksum sidecar for this dataset; the integrity
  check is the gzip member trailer (CRC-32 + ISIZE over the decompressed payload, RFC 1952
  section 2.3.1), verified on a full streaming decompress, plus a SHA-256 of the raw bytes
  that is recorded for the audit trail. A truncated or bit-flipped file fails the CRC.
* **Bounds.** Download size cap, decompressed size cap (zip-bomb guard), per-call timeouts,
  `CV_IMPORT_MAX_CONCURRENCY` concurrent downloads and a `CV_IMPORT_MAX_MBPS` byte bucket so
  an import never starves live ingestion (C-12.7: unauthenticated but still bounded).
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import hashlib
import io
import re
import time
import zlib
from collections.abc import Awaitable, Callable, Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from candleviewer.domain.archive import (
    ArchiveChecksumFailed,
    ArchiveError,
    ArchiveFile,
    ArchiveNotFound,
    ArchiveParseFailed,
    ArchiveRangeInvalid,
    ArchiveTooLarge,
    ArchiveTrade,
)

ALLOWED_ARCHIVE_HOSTS: frozenset[str] = frozenset({"public.bybit.com"})
DEFAULT_ARCHIVE_BASE = "https://public.bybit.com"
_SYMBOL = re.compile(r"^[A-Z0-9]{2,20}USDT$")
_COLUMNS = frozenset(
    {
        "timestamp", "symbol", "side", "size", "price", "tickDirection", "trdMatchID",
        "grossValue", "homeNotional", "foreignNotional",
    }
)  # fmt: skip
_SIDES = {"Buy": "buy", "Sell": "sell"}
_US_PER_S = Decimal(1_000_000)
_DAY_US = 86_400_000_000
_CHUNK = 64 * 1024
MAX_RANGE_DAYS = 366


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class ArchiveConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = DEFAULT_ARCHIVE_BASE
    max_concurrency: int = Field(default=2, ge=1, le=16)
    max_mbps: float = Field(default=50.0, gt=0.0, le=10_000.0)
    max_download_mb: int = Field(default=1024, ge=1)
    max_uncompressed_mb: int = Field(default=2048, ge=1)
    connect_timeout_s: float = Field(default=10.0, gt=0.0)
    read_timeout_s: float = Field(default=60.0, gt=0.0)
    file_timeout_s: float = Field(default=1800.0, gt=0.0)

    @field_validator("base_url")
    @classmethod
    def _pin_host(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("archive base_url must use https://")
        rest = value.removeprefix("https://").rstrip("/")
        if "/" in rest or "?" in rest or "@" in rest:
            raise ValueError("archive base_url must be a bare origin")
        if rest not in ALLOWED_ARCHIVE_HOSTS:
            raise ValueError(f"archive host {rest!r} is not allow-listed")
        return f"https://{rest}"


class ByteRateLimiter:
    """Token bucket over bytes (`max_mbps` megabits/s, burst = one second's worth).

    Clock and sleep are injectable so tests assert the cap under a fake clock. `acquire(n)`
    blocks until `n` bytes of budget exist; chunks larger than the burst are paid in parts.
    """

    def __init__(
        self,
        max_mbps: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.rate_bps = max_mbps * 1_000_000 / 8  # bytes per second
        self._capacity = self.rate_bps
        self._tokens = self._capacity
        self._clock = clock
        self._sleep = sleep
        self._at = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + max(0.0, now - self._at) * self.rate_bps)
        self._at = now

    async def acquire(self, nbytes: int) -> None:
        """Debt model: consume, then sleep off any deficit. No retry loop, so float rounding
        can never spin; the lock serialises callers so the debt is paid before the next."""
        async with self._lock:
            self._refill()
            self._tokens -= float(nbytes)
            if self._tokens < 0:
                await self._sleep(-self._tokens / self.rate_bps)
                self._refill()


def _day_bounds_us(day: date) -> tuple[int, int]:
    lo = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()) * 1_000_000
    return lo, lo + _DAY_US


class BybitTradeArchive:
    """`TradeArchiveSource` over Bybit's public trade archive."""

    def __init__(
        self,
        config: ArchiveConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        limiter: ByteRateLimiter | None = None,
    ) -> None:
        self._cfg = config or ArchiveConfig()
        self._client = client
        self._owns_client = client is None
        self._limiter = limiter or ByteRateLimiter(self._cfg.max_mbps)
        self._slots = asyncio.Semaphore(self._cfg.max_concurrency)

    @property
    def max_concurrency(self) -> int:
        return self._cfg.max_concurrency

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self._cfg.read_timeout_s, connect=self._cfg.connect_timeout_s
                ),
                follow_redirects=False,
                verify=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def list_files(self, symbol: str, start: date, end: date) -> list[ArchiveFile]:
        if not _SYMBOL.fullmatch(symbol):
            raise ArchiveRangeInvalid("unknown symbol shape")
        if end < start or (end - start).days + 1 > MAX_RANGE_DAYS:
            raise ArchiveRangeInvalid("invalid date range")
        out: list[ArchiveFile] = []
        day = start
        while day <= end:
            out.append(ArchiveFile(symbol, day, f"{symbol}{day.isoformat()}.csv.gz"))
            day += timedelta(days=1)
        return out

    def url_for(self, file: ArchiveFile) -> str:
        # Re-validate: a caller-built ArchiveFile must still match the allow-listed pattern.
        if not _SYMBOL.fullmatch(file.symbol) or file.name != (
            f"{file.symbol}{file.day.isoformat()}.csv.gz"
        ):
            raise ArchiveRangeInvalid("archive file name does not match the allowed pattern")
        return f"{self._cfg.base_url}/trading/{file.symbol}/{file.name}"

    async def fetch(self, file: ArchiveFile) -> bytes:
        url = self.url_for(file)
        cap = self._cfg.max_download_mb * 1024 * 1024
        async with self._slots:
            async with asyncio.timeout(self._cfg.file_timeout_s):
                async with self._http().stream("GET", url) as resp:
                    if resp.status_code == 404:
                        raise ArchiveNotFound("archive file not published")
                    if resp.status_code != 200:
                        raise ArchiveError(f"archive download failed: HTTP {resp.status_code}")
                    declared = resp.headers.get("content-length")
                    if declared is not None and declared.isdigit() and int(declared) > cap:
                        raise ArchiveTooLarge("archive file exceeds the download cap")
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes(_CHUNK):
                        await self._limiter.acquire(len(chunk))
                        buf.extend(chunk)
                        if len(buf) > cap:
                            raise ArchiveTooLarge("archive file exceeds the download cap")
        logger().info(
            "archive_fetched", symbol=file.symbol, day=file.day.isoformat(), bytes=len(buf)
        )
        return bytes(buf)

    def _inflate(self, raw: bytes) -> Iterator[bytes]:
        """Streaming gunzip with an absolute decompressed-size cap (zip-bomb guard)."""
        cap = self._cfg.max_uncompressed_mb * 1024 * 1024
        total = 0
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as gz:
                while chunk := gz.read(_CHUNK):
                    total += len(chunk)
                    if total > cap:
                        raise ArchiveTooLarge("decompressed size exceeds the cap")
                    yield chunk
        except (OSError, EOFError, zlib.error) as exc:
            raise ArchiveChecksumFailed("gzip integrity check failed") from exc

    def verify_checksum(self, file: ArchiveFile, raw: bytes) -> str:
        if raw[:2] != b"\x1f\x8b":
            raise ArchiveChecksumFailed("not a gzip archive")
        for _ in self._inflate(raw):  # CRC-32 + ISIZE are checked at member end
            pass
        return hashlib.sha256(raw).hexdigest()

    def _lines(self, raw: bytes) -> Iterator[str]:
        pending = b""
        for chunk in self._inflate(raw):
            pending += chunk
            *done, pending = pending.split(b"\n")
            for line in done:
                yield line.decode("utf-8")
        if pending:
            yield pending.decode("utf-8")

    def parse(
        self, file: ArchiveFile, raw: bytes, batch_rows: int
    ) -> Iterator[Sequence[ArchiveTrade]]:
        """Schema (exact column set), side vocabulary, positive Decimal price/size, monotonic
        `ts` and every `ts` inside the file's nominal UTC day; any violation fails the file."""
        lo, hi = _day_bounds_us(file.day)
        try:
            reader = csv.DictReader(self._lines(raw))
            if reader.fieldnames is None or frozenset(reader.fieldnames) != _COLUMNS:
                raise ArchiveParseFailed("unexpected column set")
            batch: list[ArchiveTrade] = []
            last = lo
            for rec in reader:
                row = self._row(file, rec)
                if not lo <= row.ts_us < hi:
                    raise ArchiveParseFailed("timestamp outside the file's nominal date")
                if row.ts_us < last:
                    raise ArchiveParseFailed("timestamps are not monotonic")
                last = row.ts_us
                batch.append(row)
                if len(batch) >= batch_rows:
                    yield batch
                    batch = []
            if batch:
                yield batch
        except UnicodeDecodeError as exc:
            raise ArchiveParseFailed("archive is not UTF-8 text") from exc
        except csv.Error as exc:
            raise ArchiveParseFailed("malformed CSV") from exc

    @staticmethod
    def _row(file: ArchiveFile, rec: dict[str, Any]) -> ArchiveTrade:
        side = _SIDES.get(str(rec.get("side")))
        if side is None or rec.get("symbol") != file.symbol:
            raise ArchiveParseFailed("unexpected side or symbol")
        trade_id = str(rec.get("trdMatchID") or "")
        if not trade_id or len(trade_id) > 64:
            raise ArchiveParseFailed("missing or oversized trade id")
        try:
            ts = Decimal(str(rec["timestamp"]))
            price = Decimal(str(rec["price"]))
            size = Decimal(str(rec["size"]))
        except (InvalidOperation, KeyError) as exc:
            raise ArchiveParseFailed("non-numeric timestamp, price or size") from exc
        if not (ts.is_finite() and price.is_finite() and size.is_finite()):
            raise ArchiveParseFailed("non-finite value")
        if price <= 0 or size <= 0:
            raise ArchiveParseFailed("non-positive price or size")
        tick = rec.get("tickDirection")
        return ArchiveTrade(
            ts_us=int(ts * _US_PER_S),
            symbol=file.symbol,
            side="buy" if side == "buy" else "sell",
            price=price,
            size=size,
            trade_id=trade_id,
            tick_dir=str(tick) if tick else None,
        )
