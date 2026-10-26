"""#2893 S10: the fixture clock and per-key runtime switching (ADR-0036 decisions 5 to 7).

The pack is the checkout's; the request log, the clock file and the key files sit under `tmp_path`.
Real time is a fake the tests move, which the fixture clock reads plus its file's offset. Requests
are signed as M2 signs them (`test_transport_guards`), at real time's `NOW`. No socket opens and
nothing sleeps.
"""

from __future__ import annotations

import errno
import json
import os
import string
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.bybit.key_info import KEY_INFO_PATH
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.settings import Environment
from cvdev.account_fixture import guards, wiring
from cvdev.account_fixture.control import (
    CLOCK_FILE,
    KEYS_DIR,
    FixtureClock,
    KeyStateError,
    KeyStates,
)
from cvdev.account_fixture.guards import FUND_PATH_PREFIX
from cvdev.account_fixture.pack import OVERLAY
from cvdev.account_fixture.requestlog import FILE_NAME, RequestLog
from cvdev.account_fixture.transport import FixtureTransport
from tests._account_fixtures import PACK, manifest
from tests.unit.cvdev.test_transport_guards import NON_FIXTURE_KEY, _get, _key, _of
from tests.unit.cvdev.test_transport_serving import KEY_IDS, WALLET, FakeClock
from tests.unit.exchange.bybit.test_account_fixture_pack import KEY_SCENARIOS, NOW, NOW_MS

#: Plan section 9.3: the cases that switch a stored key's scenario at runtime.
SWITCHING: Final = {126, 127, 128, 129, 132, 134, 204, 212, 404, 405, 410, 411, 412}
STORED: Final = "compliant"
POSITIONS, ORDERS = "/v5/position/list", "/v5/order/realtime"
SEEDED: Final = ("open_position_btcusdt_5x_sl", "working_orders_2", "history_round_trip")


def _switching(name: str) -> bool:
    cases = manifest(name)["expected"]["cases"]
    return any(
        int(case.removeprefix("E27-TC-").rstrip(string.ascii_lowercase)) in SWITCHING
        for case in cases
    )


#: The key scenarios those cases switch a stored key to, by the pack's case lists.
TARGETS: Final = [name for name in KEY_SCENARIOS if _switching(name)]


@dataclass
class Real:
    """Real time, moved by hand: what the fixture clock adds its offset to."""

    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Stack:
    transport: FixtureTransport
    keys: KeyStates
    clock: FakeClock
    latch: threading.Event
    log: RequestLog
    directory: Path

    def lines(self) -> list[dict[str, Any]]:
        text = (self.directory / FILE_NAME).read_text()
        return [json.loads(line) for line in text.splitlines()]

    def another(self) -> FixtureTransport:
        """A second transport in the same process."""
        return _transport(self.log, self.clock, self.keys, self.latch)

    async def send(self, request: httpx.Request) -> tuple[int, Any]:
        response = await self.transport.handle_async_request(request)
        return response.status_code, json.loads(await response.aread())


def _transport(
    log: RequestLog, clock: Callable[[], datetime], keys: KeyStates, latch: threading.Event
) -> FixtureTransport:
    gate = ReadOnlyGate()
    return FixtureTransport(
        PACK, log=log, gate=gate, clock=clock, default=STORED, keys=keys, latch=latch
    )


@pytest.fixture
def boot(tmp_path: Path) -> Iterator[Callable[[], Stack]]:
    """Each call boots a stack on the same state directory and clock: a restart."""
    clock = FakeClock()
    with RequestLog(
        tmp_path, process_env=Environment.DEMO, clock=clock, pack_key_ids=KEY_IDS
    ) as log:

        def build() -> Stack:
            keys, latch = KeyStates(tmp_path, PACK, log=log, clock=clock), threading.Event()
            return Stack(_transport(log, clock, keys, latch), keys, clock, latch, log, tmp_path)

        yield build


@pytest.fixture
def stack(boot: Callable[[], Stack]) -> Stack:
    return boot()


def test_the_fixture_clock_is_real_time_plus_its_files_offset(tmp_path: Path) -> None:
    real = Real()
    clock = FixtureClock(tmp_path, now=real)
    assert clock() == NOW  # no file, no offset
    clock.advance(timedelta(hours=1, microseconds=5))
    real.now += timedelta(seconds=2)
    assert clock() == NOW + timedelta(hours=1, seconds=2, microseconds=5)
    clock.set(NOW - timedelta(days=3))
    assert FixtureClock(tmp_path, now=real)() == NOW - timedelta(days=3)  # a restart keeps it
    assert (tmp_path / CLOCK_FILE).read_text() == "-259202.000000"
    assert os.listdir(tmp_path) == [CLOCK_FILE]  # renamed into place, nothing staged left
    assert FixtureClock(tmp_path)().utcoffset() == timedelta(0)  # real UTC by default


@pytest.mark.parametrize(
    "moment",
    [NOW + timedelta(seconds=10**9), NOW - timedelta(seconds=10**9), NOW.replace(tzinfo=None)],
    ids=["ahead", "behind", "naive"],
)
def test_the_fixture_clock_refuses_an_offset_its_file_cannot_hold(
    tmp_path: Path, moment: datetime
) -> None:
    with pytest.raises(ValueError, match="fixture clock"):
        FixtureClock(tmp_path, now=Real()).set(moment)
    assert os.listdir(tmp_path) == []


async def test_the_fixture_clock_never_moves_auth_time(tmp_path: Path) -> None:
    """Scenario and exchange time follow the fixture clock. The request still signs on real time,
    which the stub never judges, so a 2-day advance changes no verdict; the auth clock (#2086)
    has no file here to move."""
    real = Real()
    clock = FixtureClock(tmp_path, now=real)
    with RequestLog(
        tmp_path, process_env=Environment.DEMO, clock=clock, pack_key_ids=KEY_IDS
    ) as log:
        keys = KeyStates(tmp_path, PACK, log=log, clock=clock)
        transport = _transport(log, clock, keys, threading.Event())
        clock.advance(timedelta(days=2))
        response = await transport.handle_async_request(_get(STORED))  # signed at real NOW
    assert json.loads(await response.aread())["time"] == NOW_MS + 2 * 86_400_000
    [line] = [json.loads(text) for text in (tmp_path / FILE_NAME).read_text().splitlines()]
    assert _of(line, "outcome", "verified", "ts") == ("served", True, "2026-10-18T09:00:00.000Z")
    assert real() == NOW and sorted(os.listdir(tmp_path)) == [CLOCK_FILE, KEYS_DIR, FILE_NAME]


@pytest.mark.parametrize("target", TARGETS)
async def test_a_stored_key_switched_answers_as_its_target(stack: Stack, target: str) -> None:
    """Keeping its key id, secret and account: the plan section 9.3 switching cases."""
    assert (await stack.send(_get(STORED)))[0] == 200  # stored: its scenario starts
    stack.keys.switch(_key(STORED), target)
    switched = [await stack.send(_get(STORED, path=path)) for path in (KEY_INFO_PATH, WALLET)]
    own = [await stack.send(_get(target, path=path)) for path in (KEY_INFO_PATH, WALLET)]
    assert switched == own
    names = ("outcome", "signing_key_id", "scenario", "stored_under", "transport", "verified")
    lines = stack.lines()
    assert _of(lines[1], *names) == ("switch", _key(STORED), target, STORED, None, None)
    assert {_of(line, *names[2:4], "verified") for line in lines[2:4]} == {(target, STORED, True)}


async def test_a_switched_key_keeps_the_account_it_is_stored_on(stack: Stack) -> None:
    """close_rejected's key sits on a sub account; withdraw_enabled's manifest names the main."""
    stack.keys.switch(_key("close_rejected"), "withdraw_enabled")
    result = (await stack.send(_get("close_rejected")))[1]["result"]
    assert result["permissions"]["Wallet"] == ["Withdraw"]
    assert _of(result, "userID", "isMaster", "parentUid") == (90000011, False, "90000001")


async def test_stored_key_rejected_switches_to_its_switch_to_and_keeps_its_secret(
    stack: Stack,
) -> None:
    """TC-134: the key id still names the scenario it was stored under, whose derived secret the
    signature is checked against (scope 6); the switched-to scenario's secret is a mismatch."""
    name, target = "stored_key_rejected", "live_key_on_demo"
    before = (await stack.send(_get(name)))[1]["retCode"]
    assert stack.keys.switch(_key(name)).scenario == target
    after = (await stack.send(_get(name)))[1]["retCode"]
    mismatch = (await stack.send(_get(name, signed_as=target)))[1]["retCode"]
    assert (before, after, mismatch) == (0, 10003, 10004)
    assert [
        _of(line, "outcome", "scenario", "stored_under", "verified") for line in stack.lines()
    ] == [
        ("served", name, name, True),
        ("switch", target, name, None),
        ("served", target, name, True),
        ("signature_mismatch", None, name, False),
    ]


@pytest.mark.parametrize("key", [STORED, "ws_blip_20s"])
async def test_ws_blip_20s_switched_in_once_stored_counts_from_the_switch(
    stack: Stack, key: str
) -> None:
    """TC-411's T0 is the switch, never the key's first call, even for the blip's own key."""
    await stack.send(_get(key, path=WALLET))  # stored
    stack.clock.advance(seconds=15)
    stack.keys.switch(_key(key), "ws_blip_20s")
    switched_at, statuses = stack.clock.now, []
    for at_ms in (0, 9_999, 10_000, 29_999, 30_000):
        stack.clock.now = switched_at + timedelta(milliseconds=at_ms)
        statuses.append((await stack.send(_get(key, path=WALLET)))[0])
    assert statuses == [200, 200, 503, 503, 200]


async def test_the_three_overlays_seed_one_keys_state_through_a_switch(stack: Stack) -> None:
    """Decision 7's seeding path: a switch to the key's own scenario with overlays named."""
    stack.keys.switch(_key(STORED), STORED, overlays=SEEDED)
    lists = [
        (await stack.send(_get(STORED, path=path)))[1]["result"]["list"]
        for path in (POSITIONS, ORDERS, "/v5/order/history", "/v5/execution/list")
    ]
    other = (await stack.send(_get("compliant_alt", path=POSITIONS)))[1]["result"]["list"]
    assert ([len(found) for found in lists], other) == ([1, 2, 2, 2], [])
    assert _of(stack.lines()[0], "outcome", "scenario", "overlays") == (
        "switch",
        STORED,
        list(SEEDED),
    )
    assert all(manifest(name)["origin"] == OVERLAY and _switching(name) for name in SEEDED[:2])


async def test_a_switch_and_a_keys_start_survive_a_restart(boot: Callable[[], Stack]) -> None:
    first = boot()
    created = (await first.send(_get(STORED)))[1]["result"]["createdAt"]
    first.keys.switch(_key("compliant_alt"), "ws_blip_20s")
    first.clock.advance(seconds=15)
    second = boot()
    assert (await second.send(_get(STORED)))[1]["result"]["createdAt"] == created
    assert (await second.send(_get("compliant_alt", path=WALLET)))[0] == 503  # 15 s into it


async def test_an_anchor_never_overwrites_a_switch_made_meanwhile(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    switched = stack.keys.switch(_key(STORED), "ws_blip_20s")
    read, calls = stack.keys.read, []

    def racing(key_id: str) -> Any:  # the switch lands between the read and the anchor's link
        calls.append(key_id)
        return None if len(calls) == 1 else read(key_id)

    monkeypatch.setattr(stack.keys, "read", racing)
    assert stack.keys.anchor(_key(STORED), NOW + timedelta(hours=1)) == switched
    assert os.listdir(stack.directory / KEYS_DIR) == [f"{_key(STORED)}.json"]


@pytest.mark.parametrize(
    ("key_id", "target", "overlays"),
    [
        (NON_FIXTURE_KEY, STORED, ()),
        ("fixture-compliant-9999", STORED, ()),
        (_key(STORED), "no_such_scenario", ()),
        (_key(STORED), "working_orders_2", ()),
        (_key(STORED), "rotation_ok", ()),
        (_key(STORED), "../compliant", ()),
        (_key(STORED), None, ()),
        (_key(STORED), STORED, ("compliant",)),
        (_key(STORED), STORED, ("working_orders_2", "working_orders_2")),
    ],
    ids=[
        "non-fixture-key",
        "not-a-pack-key",
        "unknown",
        "overlay",
        "rotation-pair",
        "path",
        "no-switch-to",
        "not-an-overlay",
        "overlay-twice",
    ],
)
def test_a_switch_off_the_pack_is_refused(
    stack: Stack, key_id: str, target: str | None, overlays: tuple[str, ...]
) -> None:
    with pytest.raises(ValueError) as refused:
        stack.keys.switch(key_id, target, overlays=overlays)
    assert NON_FIXTURE_KEY not in str(refused.value)
    assert not os.listdir(stack.directory / KEYS_DIR)
    assert not (stack.directory / FILE_NAME).read_text()


async def test_a_switched_key_still_meets_every_guard_first(stack: Stack) -> None:
    """Host, fund path, key id, then the process-wide latch: another transport refuses too."""
    stack.keys.switch(_key(STORED), "ws_blip_20s")
    for request, outcome in (
        (_get(STORED, origin="https://api.bybit.com"), "refused_host"),
        (_get(STORED, path=f"{FUND_PATH_PREFIX}x"), "refused_fund_path"),
        (_get(key=NON_FIXTURE_KEY), "refused_key"),  # trips the latch
    ):
        with pytest.raises(httpx.ConnectError, match=outcome):
            await stack.transport.handle_async_request(request)
    for transport in (stack.transport, stack.another()):
        with pytest.raises(httpx.ConnectError, match="refused_key"):
            await transport.handle_async_request(_get(STORED))
    assert stack.latch.is_set()
    assert [line["outcome"] for line in stack.lines()] == [
        "switch",
        "refused_host",
        "refused_fund_path",
        *["refused_key"] * 3,
    ]


_STATE: Final = {"scenario": STORED, "overlays": [], "started": NOW.isoformat()}


@pytest.mark.parametrize(
    "content",
    [
        b"{",
        b"[]",
        b"[" * 4000,
        json.dumps(_STATE | {"scenario": "working_orders_2"}).encode(),
        json.dumps(_STATE | {"scenario": ["compliant"]}).encode(),
        json.dumps(_STATE | {"overlays": ["compliant"]}).encode(),
        json.dumps(_STATE | {"overlays": [["x"]]}).encode(),
        json.dumps(_STATE | {"overlays": {"working_orders_2": 1}}).encode(),
        json.dumps(_STATE | {"started": "2026-10-16T09:00:00"}).encode(),
        json.dumps(_STATE | {"extra": 1}).encode(),
        json.dumps(_STATE | {"overlays": ["working_orders_2"] * 1000}).encode(),
        "directory",
        "symlink",
    ],
    ids=[
        "json",
        "list",
        "deep",
        "overlay",
        "type",
        "not-an-overlay",
        "overlay-type",
        "overlay-dict",
        "naive",
        "extra",
        "too-big",
        "directory",
        "symlink",
    ],
)
async def test_a_key_file_off_the_rules_is_refused_never_answered(
    stack: Stack, content: bytes | str
) -> None:
    path = stack.directory / KEYS_DIR / f"{_key(STORED)}.json"
    if content == "directory":
        path.mkdir()
    elif content == "symlink":
        (stack.directory / "elsewhere.json").write_text(json.dumps(_STATE))
        path.symlink_to(stack.directory / "elsewhere.json")
    else:
        assert isinstance(content, bytes)
        path.write_bytes(content)
    with capture_logs() as events, pytest.raises(httpx.ConnectError, match="key_state_invalid"):
        await stack.transport.handle_async_request(_get(STORED))
    assert [_of(e, "log_level", "event") for e in events] == [
        ("error", "exchange.account_fixture_key_state_invalid")
    ]
    assert not (stack.directory / FILE_NAME).read_text()


def test_a_symlinked_keys_directory_is_refused(stack: Stack, tmp_path: Path) -> None:
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / KEYS_DIR).symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symlink"):
        KeyStates(tmp_path / "other", PACK, log=stack.log, clock=stack.clock)


_REFUSED: Final = "the account fixture transport refused the request: "


@pytest.fixture
def clocked(tmp_path: Path) -> Iterator[FixtureTransport]:
    """A stack on the fixture clock, whose file a test then breaks."""
    clock = FixtureClock(tmp_path, now=Real())
    with RequestLog(
        tmp_path, process_env=Environment.DEMO, clock=clock, pack_key_ids=KEY_IDS
    ) as log:
        keys = KeyStates(tmp_path, PACK, log=log, clock=clock)
        yield _transport(log, clock, keys, threading.Event())


@pytest.mark.parametrize("broken", ["malformed", "fifo", "symlink"])
async def test_a_clock_file_off_its_rule_refuses_by_a_fixed_code(
    clocked: FixtureTransport, tmp_path: Path, broken: str
) -> None:
    """Read for the answer (`clock_invalid`) or only for the log line (`request_log_failed`); a
    refusal stands. No message or event names the path."""
    path = tmp_path / CLOCK_FILE
    if broken == "fifo":
        os.mkfifo(path)
    elif broken == "symlink":
        (tmp_path / "elsewhere").write_text("1")
        path.symlink_to(tmp_path / "elsewhere")
    else:
        path.write_text("soon")
    cases = [
        (_get(STORED), "clock_invalid"),
        (_get(STORED, signed_as="compliant_alt"), "request_log_failed"),
        (_get(STORED, origin="https://api.bybit.com"), "refused_host"),
    ]
    with capture_logs() as events:
        for request, code in cases:
            with pytest.raises(httpx.ConnectError) as refused:
                await clocked.handle_async_request(request)
            assert (str(refused.value), refused.value.__cause__) == (_REFUSED + code, None)
            assert refused.value.__context__ is None  # nothing caught rides along, nor its path
    assert [e["event"].removeprefix("exchange.account_fixture_") for e in events] == [
        "clock_invalid",
        "signature_mismatch",
        "log_failed",
        "refused",
        "log_failed",
    ]
    assert str(tmp_path) not in repr(events)
    assert not (tmp_path / FILE_NAME).read_text()


@pytest.mark.parametrize("change", ["symlink", "removed"])
async def test_a_keys_directory_changed_after_boot_is_refused_never_followed(
    stack: Stack, change: str
) -> None:
    keys, elsewhere = stack.directory / KEYS_DIR, stack.directory / "elsewhere"
    elsewhere.mkdir()
    if change == "symlink":
        keys.rename(stack.directory / "held")
        keys.symlink_to(elsewhere)
    else:
        keys.rmdir()
    with capture_logs() as events, pytest.raises(httpx.ConnectError) as refused:
        await stack.transport.handle_async_request(_get(STORED))
    assert str(refused.value) == _REFUSED + "key_state_invalid"
    assert (refused.value.__cause__, refused.value.__context__) == (None, None)
    with pytest.raises(KeyStateError, match="held since boot"):
        stack.keys.switch(_key(STORED), "ws_blip_20s")
    assert [e["event"] for e in events] == ["exchange.account_fixture_key_state_invalid"]
    assert os.listdir(elsewhere) == [] and not (stack.directory / FILE_NAME).read_text()


async def test_a_key_file_that_cannot_be_linked_is_refused_by_a_fixed_code(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = stack.directory / KEYS_DIR

    def denied(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(errno.EACCES, "Permission denied", str(keys / _key(STORED)))

    monkeypatch.setattr(os, "link", denied)
    with capture_logs() as events, pytest.raises(httpx.ConnectError) as refused:
        await stack.transport.handle_async_request(_get(STORED))
    assert (str(refused.value), refused.value.__cause__) == (_REFUSED + "key_state_invalid", None)
    assert refused.value.__context__ is None  # the PermissionError, and its path, is not kept
    assert [e["event"] for e in events] == ["exchange.account_fixture_key_state_invalid"]
    assert str(keys) not in repr(events) and os.listdir(keys) == []


def test_a_write_that_fails_leaves_nothing_staged(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rename onto a directory, for a switch and for the clock, and a write that fails."""
    keys, name = stack.directory / KEYS_DIR, f"{_key(STORED)}.json"
    (keys / name).mkdir()
    with pytest.raises(IsADirectoryError):
        stack.keys.switch(_key(STORED), "ws_blip_20s")
    (stack.directory / CLOCK_FILE).mkdir()
    with pytest.raises(IsADirectoryError):
        FixtureClock(stack.directory, now=Real()).set(NOW)
    (keys / name).rmdir()

    def full(_fd: int, _data: object) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "write", full)
    with pytest.raises(OSError, match="No space"):
        stack.keys.switch(_key(STORED), "ws_blip_20s")
    monkeypatch.undo()
    assert os.listdir(keys) == []
    assert sorted(os.listdir(stack.directory)) == [CLOCK_FILE, KEYS_DIR, FILE_NAME]


def test_an_anchor_gives_up_on_a_key_file_that_keeps_changing(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each link meets a file the next read misses: three attempts, then a refusal."""
    path, reads = stack.directory / KEYS_DIR / f"{_key(STORED)}.json", []
    path.write_text(json.dumps(_STATE))

    def renamed_away(key_id: str) -> None:
        reads.append(key_id)

    monkeypatch.setattr(stack.keys, "read", renamed_away)
    with pytest.raises(KeyStateError, match="kept changing"):
        stack.keys.anchor(_key(STORED), NOW)
    assert len(reads) == 3 and os.listdir(path.parent) == [path.name]


@pytest.fixture
def process_latch() -> Iterator[threading.Event]:
    """The default latch, `guards.LATCH`, for the one test of it; every other test injects its
    own. Cleared after, so no tripped latch reaches another test (a stack clears it by restart)."""
    assert not guards.LATCH.is_set()
    yield guards.LATCH
    guards.LATCH.clear()


async def test_a_transport_built_without_a_latch_shares_the_process_latch(
    stack: Stack, process_latch: threading.Event
) -> None:
    """One built after a trip refuses too; an injected latch stays its own."""

    def default() -> FixtureTransport:
        gate = ReadOnlyGate()  # each its own: only the latch refuses
        return FixtureTransport(
            PACK, log=stack.log, gate=gate, clock=stack.clock, default=STORED, keys=stack.keys
        )

    first = default()
    assert wiring.LATCH is process_latch
    with pytest.raises(httpx.ConnectError, match="refused_key"):
        await first.handle_async_request(_get(key=NON_FIXTURE_KEY))
    assert process_latch.is_set() and not stack.latch.is_set()
    for transport in (first, default()):
        with pytest.raises(httpx.ConnectError, match="refused_key"):
            await transport.handle_async_request(_get(STORED))
    assert not stack.transport.latched


async def test_a_request_reads_the_clock_off_the_event_loop(stack: Stack) -> None:
    """With the key's file, in one thread (`select`): the clock is a file read on a stack."""
    loop, seen = threading.get_ident(), []

    def clock() -> datetime:
        seen.append(threading.get_ident())
        return NOW

    transport = _transport(stack.log, clock, stack.keys, stack.latch)
    seen.clear()  # the constructor's boot read
    for _ in range(2):
        assert (await transport.handle_async_request(_get(STORED))).status_code == 200
    assert len(seen) == 2 and loop not in seen
