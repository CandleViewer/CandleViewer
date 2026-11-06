"""The admin chaos suite's own helpers (E42-Q03, #1216): the relay, the target guard and the alert
chain's promtool input. Pure and loopback only, so the PR lane runs them (marker `chaos`, no
`harness`); the scenarios that use them need Postgres and run nightly.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import yaml
from prometheus_client import CollectorRegistry, Counter

from candleviewer.admin.backups.metrics import EXPORTED_NAMES as BACKUP_NAMES
from candleviewer.observability.audit_query_metrics import EXPORTED_NAMES as AUDIT_NAMES
from tests.chaos.admin import _alerts
from tests.chaos.admin._relay import HOST, SSL_REQUEST, Mode, Relay, upstream_of
from tests.chaos.admin._server import HarnessRefused, problem_is_clean, require_test_database

pytestmark = pytest.mark.chaos

BOUND_S = 2.0  # every wait here; a hang fails the test, never the lane
#: The Postgres SSLRequest as the wire carries it, written out rather than read from the module, so
#: a changed request is not answered.
WIRE_SSL_REQUEST = b"\x00\x00\x00\x08\x04\xd2\x16\x2f"


async def _echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """An upstream stand-in: answers an SSLRequest `N` as Postgres does, echoes anything else."""
    while data := await reader.read(1024):
        writer.write(b"N" if data == WIRE_SSL_REQUEST else data)
        await writer.drain()
    writer.close()


async def _shut(server: asyncio.Server) -> None:
    server.close()
    async with asyncio.timeout(BOUND_S):
        await server.wait_closed()


@pytest.fixture
async def relay() -> AsyncIterator[Relay]:
    server = await asyncio.start_server(_echo, HOST, 0)
    port = int(server.sockets[0].getsockname()[1])
    async with Relay((HOST, port)) as opened:
        yield opened
    await _shut(server)


async def _link(relay: Relay) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """A client link through `relay`, live: one round trip has crossed it."""
    async with asyncio.timeout(BOUND_S):
        reader, writer = await asyncio.open_connection(HOST, relay.port)
        writer.write(b"up")
        await writer.drain()
        assert await reader.readexactly(2) == b"up"
    return reader, writer


async def _round_trip(relay: Relay, payload: bytes = b"ping") -> bytes:
    async with asyncio.timeout(BOUND_S):
        reader, writer = await asyncio.open_connection(HOST, relay.port)
        writer.write(payload)
        await writer.drain()
        got = await reader.readexactly(len(payload))
    writer.close()
    return got


async def test_relay_passes_bytes_both_ways(relay: Relay) -> None:
    assert await _round_trip(relay) == b"ping"
    await relay.ensure_up()


async def test_relay_ensure_up_fails_when_the_upstream_does_not_answer() -> None:
    async def mute(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(1024)
        writer.close()  # reaches the upstream, which hangs up without a reply

    server = await asyncio.start_server(mute, HOST, 0)
    port = int(server.sockets[0].getsockname()[1])
    async with Relay((HOST, port)) as relay:
        with pytest.raises(asyncio.IncompleteReadError):
            await relay.ensure_up()
    await _shut(server)


def test_relay_ssl_request_is_the_wire_request() -> None:
    assert SSL_REQUEST == WIRE_SSL_REQUEST


async def test_relay_listens_on_loopback_ipv4_only(relay: Relay) -> None:
    assert relay._server is not None
    assert [s.getsockname()[0] for s in relay._server.sockets] == ["127.0.0.1"]


async def test_relay_delay_set_over_a_blackhole_releases_the_held_chunks(relay: Relay) -> None:
    relay.blackhole()
    relay.delay(20)
    assert await _round_trip(relay) == b"ping"
    await relay.heal()


async def test_relay_delay_holds_each_chunk_in_each_direction(relay: Relay) -> None:
    relay.delay(100)
    started = time.monotonic()
    assert await _round_trip(relay) == b"ping"
    assert time.monotonic() - started >= 0.2  # 100 ms out, 100 ms back
    assert relay.trace == ["delay"]


async def test_relay_blackhole_forwards_nothing_and_heal_resets_the_held_link(
    relay: Relay,
) -> None:
    async with asyncio.timeout(BOUND_S):
        reader, writer = await asyncio.open_connection(HOST, relay.port)
    relay.blackhole()
    writer.write(b"lost")
    await writer.drain()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.3):
            await reader.read(4)
    await relay.heal()
    async with asyncio.timeout(BOUND_S):
        assert await reader.read(4) == b""  # reset, never the late reply
    writer.close()
    assert await _round_trip(relay) == b"ping"


async def test_relay_heal_resets_a_link_that_was_live_before_the_blackhole(relay: Relay) -> None:
    reader, writer = await _link(relay)
    relay.blackhole()
    writer.write(b"held")
    await writer.drain()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.3):
            await reader.read(4)
    await relay.heal()
    async with asyncio.timeout(BOUND_S):
        assert await reader.read(4) == b""  # reset, never the late reply
    writer.close()
    assert await _round_trip(relay) == b"ping"


async def test_relay_blackhole_holds_a_link_opened_during_it(relay: Relay) -> None:
    relay.blackhole()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(_round_trip(relay), 0.3)
    await relay.heal()
    assert await _round_trip(relay) == b"ping"


async def test_relay_cut_refuses_and_resets_then_heal_listens_on_the_same_port(
    relay: Relay,
) -> None:
    port = relay.port
    reader, writer = await _link(relay)
    relay.cut()
    async with asyncio.timeout(BOUND_S):
        assert await reader.read(4) == b""
    writer.close()
    with pytest.raises(OSError):
        await _round_trip(relay)
    await relay.heal()
    assert relay.port == port
    assert await _round_trip(relay) == b"ping"


@pytest.mark.parametrize("fault", ["delay", "blackhole", "cut"])
async def test_relay_ensure_up_fails_while_a_fault_stands(relay: Relay, fault: str) -> None:
    {"delay": lambda: relay.delay(10), "blackhole": relay.blackhole, "cut": relay.cut}[fault]()
    with pytest.raises(AssertionError, match=fault):
        await relay.ensure_up()
    await relay.heal()
    await relay.ensure_up()
    assert relay.mode is Mode.OPEN


async def test_relay_close_ends_every_link_and_task_and_the_port() -> None:
    server = await asyncio.start_server(_echo, HOST, 0)
    upstream_port = int(server.sockets[0].getsockname()[1])
    relay = Relay((HOST, upstream_port))
    await relay.__aenter__()
    reader, writer = await _link(relay)
    assert relay._tasks and relay._links
    await relay.close()
    assert relay._tasks == set() and relay._links == set() and relay._server is None
    assert relay.mode is Mode.CUT
    async with asyncio.timeout(BOUND_S):
        assert await reader.read(4) == b""  # the client side of the link was reset
    writer.close()
    with pytest.raises(OSError):
        await _round_trip(relay)
    await _shut(server)


def test_relay_through_aims_the_dsn_at_the_relay() -> None:
    dsn = "postgresql+asyncpg://cv:pw@db.example:6543/admin_world_test"
    assert upstream_of(dsn) == ("db.example", 6543)
    assert upstream_of("postgresql+asyncpg://cv@localhost/test") == ("localhost", 5432)
    relay = Relay(("localhost", 6543))
    relay.port = 40001
    assert relay.through(dsn) == "postgresql+asyncpg://cv:pw@127.0.0.1:40001/admin_world_test"


@pytest.mark.parametrize("host", ["db.internal", "10.0.0.5", "203.0.113.7"])
def test_relay_refuses_a_non_loopback_upstream_without_echoing_it(host: str) -> None:
    with pytest.raises(ValueError, match="loopback") as refused:
        Relay((host, 6543))
    assert host not in str(refused.value) and "6543" not in str(refused.value)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql+asyncpg://cv@127.0.0.1:5432/test",
        "postgresql+asyncpg://cv@localhost:5432/admin_world_test",
        "postgresql+asyncpg://cv@[::1]:5432/_test",
    ],
)
def test_guard_admits_a_loopback_database_named_for_tests(dsn: str) -> None:
    require_test_database(dsn)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql+asyncpg://cv:pw@127.0.0.1:5432/candleviewer",
        "postgresql+asyncpg://cv:pw@127.0.0.1:5432/test_admin",
        "postgresql+asyncpg://cv:pw@127.0.0.1:5432/admin_worldtest",
        "postgresql+asyncpg://cv:pw@127.0.0.1:5432/Test",
        "postgresql+asyncpg://cv:pw@db.internal:5432/admin_world_test",
        "postgresql+asyncpg://cv:pw@127.0.0.1:5432",
    ],
)
def test_guard_refuses_anything_else_without_echoing_the_dsn(dsn: str) -> None:
    with pytest.raises(HarnessRefused) as refused:
        require_test_database(dsn)
    assert "pw" not in str(refused.value) and "5432" not in str(refused.value)


_LOOPBACK_TEST_DSN = "postgresql+asyncpg://cv:pw@127.0.0.1:5432/admin_world_test"
_OUT_OF_FORM = pytest.mark.parametrize(
    "extra",
    [
        pytest.param("host=db.internal", id="out_of_form_a"),
        pytest.param("host=/var/run/postgresql", id="out_of_form_b"),
        pytest.param("dbname=candleviewer", id="out_of_form_c"),
        pytest.param("port=6543", id="out_of_form_d"),
        pytest.param("ssl=disable", id="out_of_form_e"),
    ],
)


def _quiet(refused: BaseException, extra: str) -> bool:
    text = str(refused)
    return all(mark not in text for mark in ("pw", "5432", "cv:", extra, extra.split("=")[1]))


@_OUT_OF_FORM
def test_guard_refuses_a_dsn_out_of_form_without_echoing_it(extra: str) -> None:
    with pytest.raises(HarnessRefused) as refused:
        require_test_database(f"{_LOOPBACK_TEST_DSN}?{extra}")
    assert _quiet(refused.value, extra)


@_OUT_OF_FORM
def test_relay_upstream_refuses_a_dsn_out_of_form_without_echoing_it(extra: str) -> None:
    with pytest.raises(ValueError) as refused:
        upstream_of(f"{_LOOPBACK_TEST_DSN}?{extra}")
    assert _quiet(refused.value, extra)


@_OUT_OF_FORM
def test_relay_through_refuses_a_dsn_out_of_form_without_echoing_it(extra: str) -> None:
    relay = Relay(("127.0.0.1", 5432))
    relay.port = 40001
    with pytest.raises(ValueError) as refused:
        relay.through(f"{_LOOPBACK_TEST_DSN}?{extra}")
    assert _quiet(refused.value, extra)


@pytest.mark.parametrize(
    "dsn",
    [
        pytest.param("not a dsn pw", id="unreadable_a"),
        pytest.param("postgresql+asyncpg://cv:pw@127.0.0.1:x/t_test", id="unreadable_b"),
    ],
)
def test_guards_refuse_an_unreadable_dsn_without_echoing_it(dsn: str) -> None:
    with pytest.raises(HarnessRefused) as guard:
        require_test_database(dsn)
    with pytest.raises(ValueError) as relay:
        upstream_of(dsn)
    for refused in (guard.value, relay.value):
        assert "pw" not in str(refused) and refused.__cause__ is None


@pytest.mark.parametrize(
    "body",
    ['{"detail": "Traceback (most recent call last)"}', '{"detail": "at 127.0.0.1:40001"}'],
)
def test_problem_is_clean_finds_a_trace_or_a_hidden_value(body: str) -> None:
    assert problem_is_clean('{"code": "store_unavailable"}', ":40001")
    assert not problem_is_clean(body, ":40001")


@pytest.mark.parametrize(
    ("alertname", "series"),
    [
        ("AuditChainVerificationFailed", "audit_chain_verification_failures_total"),
        ("AuditBreakHaltEngaged", "cv_audit_break_halt_state"),
        ("BackupLastSuccessStale", "cv_backup_last_success_age_seconds"),
    ],
)
def test_the_rules_read_series_the_app_exports(alertname: str, series: str) -> None:
    """[BQ-6] A rename on either side fails here, not in production."""
    assert series in AUDIT_NAMES | BACKUP_NAMES
    assert series in str(_alerts.rule(alertname)["expr"])


def test_scrape_reads_the_text_exposition() -> None:
    registry = CollectorRegistry()
    counter = Counter("chaos_probe", "A probe.", labelnames=("env",), registry=registry)
    counter.labels("testnet").inc(2)
    assert _alerts.scrape("chaos_probe_total", registry, env="testnet") == 2.0
    assert _alerts.scrape("chaos_probe_total", registry, env="live") is None


def test_case_expects_the_rules_own_labels_and_annotations(tmp_path: Path) -> None:
    built = _alerts.case(
        "AuditChainVerificationFailed",
        {_alerts.series("audit_chain_verification_failures_total", {"env": "testnet"}): "0 1"},
        eval_time="5m",
        labels={"env": "testnet"},
    )
    expected = built["alert_rule_test"][0]["exp_alerts"][0]
    assert expected["exp_labels"] == {
        "severity": "page",
        "component": "audit",
        "resolves": "window",
        "env": "testnet",
    }
    assert expected["exp_annotations"]["summary"] == "Audit chain verification failed"
    assert built["input_series"][0]["series"] == (
        'audit_chain_verification_failures_total{env="testnet"}'
    )
    path = _alerts.write_suite("s4_chain", [built], tmp_path)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["rule_files"] == ["/p/alerts/system_page.yml", "/p/alerts/system_ticket.yml"]
    assert doc["tests"] == [built]
    with pytest.raises(KeyError):
        _alerts.rule("NoSuchAlert")


def test_out_dir_prefers_the_nightlys_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_alerts.OUT_ENV, raising=False)
    assert _alerts.out_dir(tmp_path / "local") == tmp_path / "local"
    monkeypatch.setenv(_alerts.OUT_ENV, str(tmp_path / "nightly"))
    assert _alerts.out_dir(tmp_path / "local") == tmp_path / "nightly"
    assert (tmp_path / "nightly").is_dir()
