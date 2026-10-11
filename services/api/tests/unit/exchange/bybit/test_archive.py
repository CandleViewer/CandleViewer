"""E16-T10 adapter: public trade-archive URL construction, download bounds, integrity, parse.

No network: every HTTP exchange is intercepted by respx at the transport (no socket opens), and
the settings deny list / CI network guard stay intact. Archives are the committed synthetic
fixture (tests/fixtures/archive/README.md) or built in-test.
"""

from __future__ import annotations

import gzip
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import ValidationError

from candleviewer.domain.archive import (
    ArchiveChecksumFailed,
    ArchiveError,
    ArchiveFile,
    ArchiveNotFound,
    ArchiveParseFailed,
    ArchiveRangeInvalid,
    ArchiveTooLarge,
)
from candleviewer.exchange.base.archive import TradeArchiveSource
from candleviewer.exchange.bybit.archive import (
    ArchiveConfig,
    BybitTradeArchive,
    ByteRateLimiter,
)

FIXTURE = Path(__file__).parents[3] / "fixtures" / "archive" / "BTCUSDT2026-06-05.csv.gz"
DAY = date(2026, 6, 5)
BASE = "https://public.bybit.com"
HEADER = (
    "timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,"
    "foreignNotional"
)
T0 = 1780617600  # 2026-06-05T00:00:00Z


def _file() -> ArchiveFile:
    return ArchiveFile("BTCUSDT", DAY, "BTCUSDT2026-06-05.csv.gz")


def _gz(*lines: str, header: str = HEADER) -> bytes:
    return gzip.compress(("\n".join([header, *lines]) + "\n").encode(), mtime=0)


def _row(ts: float, side: str = "Buy", price: str = "100.5", size: str = "0.1", i: int = 0) -> str:
    return f"{ts:.4f},BTCUSDT,{side},{size},{price},PlusTick,id-{i},0,{size},0"


def test_archive_adapter_satisfies_port() -> None:
    assert isinstance(BybitTradeArchive(), TradeArchiveSource)


def test_list_files_builds_names_from_symbol_and_iso_date() -> None:
    files = BybitTradeArchive().list_files("BTCUSDT", date(2026, 6, 1), date(2026, 6, 3))
    assert [f.name for f in files] == [
        "BTCUSDT2026-06-01.csv.gz", "BTCUSDT2026-06-02.csv.gz", "BTCUSDT2026-06-03.csv.gz"
    ]  # fmt: skip
    assert BybitTradeArchive().url_for(files[0]) == (
        f"{BASE}/trading/BTCUSDT/BTCUSDT2026-06-01.csv.gz"
    )


@pytest.mark.parametrize("symbol", ["btcusdt", "../etc", "BTC/USDT", "BTCUSD", "A" * 30 + "USDT"])
def test_list_files_unknown_symbol_rejected(symbol: str) -> None:
    with pytest.raises(ArchiveRangeInvalid):
        BybitTradeArchive().list_files(symbol, DAY, DAY)


def test_list_files_inverted_or_oversized_range_rejected() -> None:
    a = BybitTradeArchive()
    with pytest.raises(ArchiveRangeInvalid):
        a.list_files("BTCUSDT", date(2026, 6, 2), date(2026, 6, 1))
    with pytest.raises(ArchiveRangeInvalid):
        a.list_files("BTCUSDT", date(2025, 1, 1), date(2026, 6, 1))


@pytest.mark.parametrize(
    "name", ["../../x.csv.gz", "C:\\x", "BTCUSDT2026-06-06.csv.gz", "/abs", "BTCUSDT2026-06-05.zip"]
)
def test_url_for_rejects_names_not_from_the_pattern(name: str) -> None:
    with pytest.raises(ArchiveRangeInvalid):
        BybitTradeArchive().url_for(ArchiveFile("BTCUSDT", DAY, name))


@pytest.mark.parametrize(
    "base",
    [
        "http://public.bybit.com",
        "https://evil.example.com",
        "https://public.bybit.com/path",
        "https://user@public.bybit.com",
        "https://public.bybit.com.evil.com",
    ],
)
def test_config_pins_https_and_archive_host(base: str) -> None:
    with pytest.raises(ValidationError):
        ArchiveConfig(base_url=base)


def test_config_defaults_match_architecture_keys() -> None:
    cfg = ArchiveConfig()
    assert (cfg.max_concurrency, cfg.max_mbps, cfg.max_uncompressed_mb) == (2, 50.0, 2048)


# -- fetch (respx: transport-level fake, no socket) -------------------------------------------


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


@respx.mock
async def test_fetch_downloads_fixture_bytes() -> None:
    raw = FIXTURE.read_bytes()
    route = respx.get(f"{BASE}/trading/BTCUSDT/BTCUSDT2026-06-05.csv.gz").mock(
        return_value=httpx.Response(200, content=raw)
    )
    async with httpx.AsyncClient() as client:
        got = await BybitTradeArchive(client=client).fetch(_file())
    assert got == raw and route.call_count == 1


@respx.mock
async def test_fetch_404_is_not_found() -> None:
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        with pytest.raises(ArchiveNotFound):
            await BybitTradeArchive(client=client).fetch(_file())


@respx.mock
async def test_fetch_redirect_is_never_followed() -> None:
    respx.get(url__regex=r".*").mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.example.com/x"})
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ArchiveError):
            await BybitTradeArchive(client=client).fetch(_file())
    assert respx.calls.call_count == 1


@respx.mock
async def test_fetch_declared_size_above_cap_refused() -> None:
    respx.get(url__regex=r".*").mock(
        return_value=httpx.Response(200, content=b"x", headers={"content-length": str(2 << 20)})
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ArchiveTooLarge):
            await BybitTradeArchive(ArchiveConfig(max_download_mb=1), client=client).fetch(_file())


@respx.mock
async def test_fetch_streamed_size_above_cap_refused() -> None:
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, content=b"x" * (2 << 20)))
    async with httpx.AsyncClient() as client:
        a = BybitTradeArchive(ArchiveConfig(max_download_mb=1), client=client)
        a._cfg = ArchiveConfig(max_download_mb=1)
        with pytest.raises(ArchiveTooLarge):
            await a.fetch(_file())


@respx.mock
async def test_fetch_bytes_per_second_bounded_by_limiter_under_fake_clock() -> None:
    clock = _FakeClock()
    limiter = ByteRateLimiter(8.0, clock=clock, sleep=clock.sleep)  # 1 MB/s
    payload = b"z" * 3_000_000
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, content=payload))
    async with httpx.AsyncClient() as client:
        await BybitTradeArchive(client=client, limiter=limiter).fetch(_file())
    # burst = 1 s worth, so 3 MB at 1 MB/s needs >= 2 s of (fake) waiting
    assert clock.t >= 2.0 - 1e-6
    assert len(payload) <= limiter.rate_bps * (clock.t + 1.0)


async def test_rate_limiter_caps_bytes_per_second() -> None:
    clock = _FakeClock()
    lim = ByteRateLimiter(50.0, clock=clock, sleep=clock.sleep)  # 6.25 MB/s
    total = 0
    for _ in range(100):
        await lim.acquire(1_000_000)
        total += 1_000_000
    burst = lim.rate_bps
    assert total <= burst + lim.rate_bps * clock.t + 1


async def test_fetch_concurrency_never_exceeds_cap() -> None:
    import asyncio

    in_flight = peak = 0
    gate = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await gate.wait()
        in_flight -= 1
        return httpx.Response(200, stream=httpx.ByteStream(b"ok"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        a = BybitTradeArchive(ArchiveConfig(max_concurrency=2), client=client)
        files = a.list_files("BTCUSDT", date(2026, 6, 1), date(2026, 6, 6))
        tasks = [asyncio.ensure_future(a.fetch(f)) for f in files]
        for _ in range(20):
            await asyncio.sleep(0)
        assert peak == 2
        gate.set()
        await asyncio.gather(*tasks)
    assert peak == 2


# -- integrity + parse ------------------------------------------------------------------------


def test_verify_checksum_returns_sha256_of_fixture() -> None:
    import hashlib

    raw = FIXTURE.read_bytes()
    assert BybitTradeArchive().verify_checksum(_file(), raw) == hashlib.sha256(raw).hexdigest()


def test_verify_checksum_detects_bit_flip_and_truncation() -> None:
    raw = bytearray(FIXTURE.read_bytes())
    flipped = bytes(raw[:-8]) + bytes([raw[-8] ^ 0xFF]) + bytes(raw[-7:])  # CRC byte
    for bad in (flipped, bytes(raw[:-5]), b"PK\x03\x04junk"):
        with pytest.raises(ArchiveChecksumFailed):
            BybitTradeArchive().verify_checksum(_file(), bad)


def test_verify_checksum_zip_bomb_stopped_at_decompressed_cap() -> None:
    bomb = gzip.compress(b"\0" * (3 << 20), mtime=0)  # ~3 KiB -> 3 MiB
    with pytest.raises(ArchiveTooLarge):
        BybitTradeArchive(ArchiveConfig(max_uncompressed_mb=1)).verify_checksum(_file(), bomb)


def test_parse_fixture_yields_decimal_rows_in_order() -> None:
    rows = [r for b in BybitTradeArchive().parse(_file(), FIXTURE.read_bytes(), 4) for r in b]
    assert len(rows) == 6
    assert rows[0].price == Decimal("67012.5") and rows[1].size == Decimal("0.250")
    assert rows[0].side == "buy" and rows[1].side == "sell"
    assert rows[0].ts_us == (T0 * 1_000_000) + 123_400
    assert [r.ts_us for r in rows] == sorted(r.ts_us for r in rows)


def test_parse_batches_respect_batch_rows() -> None:
    batches = list(BybitTradeArchive().parse(_file(), FIXTURE.read_bytes(), 4))
    assert [len(b) for b in batches] == [4, 2]


@pytest.mark.parametrize(
    "raw",
    [
        _gz(_row(T0 + 1), header="timestamp,symbol,side,size,price"),
        _gz(_row(T0 + 1, side="Long")),
        _gz(_row(T0 + 5, i=1), _row(T0 + 1, i=2)),  # not monotonic
        _gz(_row(T0 - 1)),  # before the nominal date
        _gz(_row(T0 + 86_400)),  # after the nominal date
        _gz(_row(T0 + 1, price="abc")),
        _gz(_row(T0 + 1, price="-1")),
        _gz(_row(T0 + 1, size="NaN")),
        _gz(_row(T0 + 1).replace("BTCUSDT", "ETHUSDT")),
        gzip.compress(b"\xff\xfe\x00bad", mtime=0),
    ],
)
def test_parse_schema_violations_fail_the_file(raw: bytes) -> None:
    with pytest.raises(ArchiveParseFailed):
        list(BybitTradeArchive().parse(_file(), raw, 100))


# -- review hardening ---------------------------------------------------------------------------


@respx.mock
async def test_fetch_rejects_transparent_content_encoding() -> None:
    respx.get(url__regex=r".*").mock(
        return_value=httpx.Response(200, content=b"x", headers={"content-encoding": "br"})
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ArchiveError):
            await BybitTradeArchive(client=client).fetch(_file())


@respx.mock
async def test_fetch_returns_wire_bytes_not_decoded_body() -> None:
    raw = FIXTURE.read_bytes()
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, content=raw))
    async with httpx.AsyncClient() as client:
        assert await BybitTradeArchive(client=client).fetch(_file()) == raw


def test_owned_client_ignores_proxy_environment() -> None:
    client = BybitTradeArchive()._http()
    assert client.trust_env is False and client.follow_redirects is False


def test_default_download_buffer_cap_is_bounded() -> None:
    assert ArchiveConfig().max_download_mb == 256
    with pytest.raises(ValidationError):
        ArchiveConfig(max_download_mb=4096)


def test_parse_overlong_line_fails_without_unbounded_growth() -> None:
    from candleviewer.exchange.bybit.archive import MAX_LINE_BYTES

    raw = gzip.compress(HEADER.encode() + b"\n" + b"9" * (MAX_LINE_BYTES * 4), mtime=0)
    with pytest.raises(ArchiveParseFailed):
        list(BybitTradeArchive().parse(_file(), raw, 100))
