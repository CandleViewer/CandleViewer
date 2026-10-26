"""#2893 S12b: the door refuses until the boot guard passes, which then builds one transport and
one socket on it, on `guards.LATCH` and the process gate, once a process. The fixture clock reaches
the stub alone. The lifespan side is in `tests/unit/test_main_lifespan.py`."""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from candleviewer import app as app_module
from candleviewer.account_fixture_wiring import AccountFixtureRefused as Refused
from candleviewer.account_fixture_wiring import account_fixture_guard, build_account_fixture
from candleviewer.exchange.bybit import key_verify
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.settings import Environment, FeedMode, Settings
from cvdev.account_fixture import boot, guards, wiring
from cvdev.account_fixture import pack as account_pack
from cvdev.account_fixture.boot import StoredKey
from cvdev.account_fixture.control import FixtureClock, KeyStates
from cvdev.account_fixture.requestlog import FILE_NAME, RequestLog
from tests._account_fixtures import PACK, PACK_ROOT
from tests.unit.cvdev.test_transport_guards import NON_FIXTURE_KEY, _get

TIME = httpx.Request("GET", "https://api-demo.bybit.com/v5/market/time")


@pytest.fixture(autouse=True)
def _one_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No `CV_*` variable, the checkout's pack, a fresh once-a-process build, the latch clear."""
    for name in [n for n in os.environ if n.upper().startswith("CV_")]:
        monkeypatch.delenv(name)
    monkeypatch.setattr(account_pack, "PACK_ROOT", PACK_ROOT)
    monkeypatch.setattr(wiring, "_ONCE", threading.Lock())
    assert not guards.LATCH.is_set()
    yield
    guards.LATCH.clear()


@pytest.fixture
def state(tmp_path: Path) -> Path:
    (tmp_path / "state").mkdir(mode=0o700)
    return tmp_path / "state"


def _dev(state: Path | None, scenario: str = "compliant") -> Settings:
    fixture: dict[str, Any] = {
        "account_fixture": scenario,
        "account_fixture_dir": state and str(state),
    }
    return Settings(environment=Environment.DEMO, feed=FeedMode.SYNTHETIC, **fixture)


def _door(settings: Settings) -> wiring.FixtureDoor:
    fixture = build_account_fixture(settings)
    assert isinstance(fixture, wiring.FixtureDoor)
    return fixture


async def _assert_closed(door: wiring.FixtureDoor) -> None:
    """The refusing pair: no reply, no socket, nothing built."""
    with pytest.raises(httpx.ConnectError, match=re.escape(wiring.REFUSAL)):
        await door.rest_transport.handle_async_request(TIME)
    with pytest.raises(ConnectionRefusedError, match=re.escape(wiring.REFUSAL)):
        await door.private_ws_connect(guards.DEMO_PRIVATE_WS)
    assert door.armed is None


async def test_a_passed_guard_builds_one_pair_on_the_process_latch_and_gate(state: Path) -> None:
    door, gate = _door(_dev(state)), ReadOnlyGate()

    assert await account_fixture_guard(_dev(state), door, gate) is not None

    assert door.armed is not None
    assert door.armed.sockets._rest is door.armed.transport
    reply = await door.rest_transport.handle_async_request(_get("compliant"))
    await (await door.private_ws_connect(guards.DEMO_PRIVATE_WS)).close()
    log = [json.loads(line) for line in (state / FILE_NAME).read_text().splitlines()]
    assert [(n["transport"], n["outcome"]) for n in log][:2] == [
        ("rest", "served"),
        ("ws", "served"),
    ]
    assert (reply.status_code, gate.latched_reason_code) == (200, None)

    with pytest.raises(httpx.ConnectError):
        await door.rest_transport.handle_async_request(_get(key=NON_FIXTURE_KEY))

    assert guards.LATCH.is_set() and wiring.LATCH is guards.LATCH
    assert gate.latched_reason_code == guards.GUARD_REASON_CODE
    with pytest.raises(httpx.ConnectError):
        await door.rest_transport.handle_async_request(_get("compliant"))
    with pytest.raises(ConnectionRefusedError):
        await door.private_ws_connect(guards.DEMO_PRIVATE_WS)


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("live-key-stored", "1 outside demo (live 1)"),
        ("api-key-variable", "while any CV_BYBIT_API_* variable is set"),
        ("live", "unless CV_ENVIRONMENT=demo"),
        ("testnet", "unless CV_ENVIRONMENT=demo"),
    ],
)
async def test_outside_dev_test_the_boot_is_refused_and_nothing_is_built(
    state: Path, monkeypatch: pytest.MonkeyPatch, case: str, reason: str
) -> None:
    """S8 refuses a stored live key; it, and the build, re-check S2's gate (skipped validation)."""

    async def _a_live_key(settings: Settings) -> Sequence[StoredKey]:
        return [StoredKey(env="live", key_id_last4="Ab12")]

    monkeypatch.setattr(boot, "read_stored_keys", _a_live_key)
    environment = {"live": Environment.LIVE, "testnet": Environment.TESTNET}.get(case)
    settings = _dev(state).model_copy(update={"environment": environment or Environment.DEMO})
    door = wiring.FixtureDoor(settings)
    if case == "api-key-variable":
        monkeypatch.setenv("CV_BYBIT_API_KEY", "set")

    with pytest.raises(Refused, match=re.escape(reason)):
        await account_fixture_guard(settings, door, ReadOnlyGate())
    if case != "live-key-stored":  # the build's own re-check, which S8's normally pre-empts
        with pytest.raises(Refused, match=re.escape(reason)):
            await door.arm(ReadOnlyGate(), PACK)

    await _assert_closed(door)
    assert os.listdir(state) == []


async def test_the_pair_is_built_once_a_process(state: Path) -> None:
    first, second = _door(_dev(state)), _door(_dev(state))
    await first.arm(ReadOnlyGate(), PACK)
    armed = first.armed

    for door in (first, second):
        with pytest.raises(Refused, match=re.escape(wiring.BUILT_ONCE)):
            await door.arm(ReadOnlyGate(), PACK)

    assert (first.armed, second.armed) == (armed, None)
    await _assert_closed(second)


@pytest.mark.parametrize(
    ("case", "scenario"),
    [("unset", "compliant"), ("swapped", "compliant"), ("state", "open_position_btcusdt_5x_sl")],
    ids=["dir-unset", "dir-swapped-for-a-symlink", "overlay-as-default"],
)
async def test_a_failed_build_refuses_boot_with_a_fixed_message(
    state: Path, case: str, scenario: str
) -> None:
    swapped = state.parent / "swapped"
    swapped.mkdir(mode=0o700)
    door = _door(_dev({"unset": None, "swapped": swapped}.get(case, state), scenario))
    swapped.rmdir()
    swapped.symlink_to(state)  # after `Settings` checked the path

    with pytest.raises(Refused) as refused:
        await door.arm(ReadOnlyGate(), PACK)

    assert str(refused.value) == wiring.BUILD_REFUSAL and str(state) not in str(refused.value)
    assert (refused.value.__cause__, refused.value.__context__) == (None, None)
    await _assert_closed(door)


class _Stop(BaseException):
    """A cancel, say: never turned into a refusal."""


@pytest.mark.parametrize("error", [PermissionError(13, "denied", "/state/keys"), _Stop()])
async def test_a_failure_after_the_log_opens_closes_it(
    state: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    closed: list[int] = []
    real_close = RequestLog.close

    def _close(log: RequestLog) -> None:
        closed.append(1)
        real_close(log)

    def _broken(*_args: object, **_kwargs: object) -> KeyStates:
        raise error

    monkeypatch.setattr(RequestLog, "close", _close)
    monkeypatch.setattr(wiring, "KeyStates", _broken)
    door = _door(_dev(state))

    with pytest.raises((Refused, _Stop)) as refused:
        await door.arm(ReadOnlyGate(), PACK)

    expected = wiring.BUILD_REFUSAL if isinstance(error, Exception) else ""
    assert (str(refused.value), refused.value.__context__, closed) == (expected, None, [1])
    await _assert_closed(door)


@pytest.mark.parametrize("handle", ["not-the-door", "no-gate"])
async def test_the_guard_refuses_a_handle_it_cannot_build(state: Path, handle: str) -> None:
    door = _door(_dev(state))
    fixture: Any = object() if handle == "not-the-door" else door
    gate = None if handle == "no-gate" else ReadOnlyGate()

    with pytest.raises(Refused, match=re.escape(wiring.NOT_BUILDABLE)):
        await account_fixture_guard(_dev(state), fixture, gate)

    await _assert_closed(door)


async def test_the_fixture_clock_is_injected_into_no_client(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture clock is the stub's only: a day ahead, the adapter still signs on real time."""
    seen: list[Any] = []

    def spy(*args: Any, **kwargs: Any) -> BybitRestClient:
        client = BybitRestClient(*args, **kwargs)
        seen.extend([*kwargs.values(), client._wall_clock])
        return client

    monkeypatch.setattr(key_verify, "BybitRestClient", spy)
    app = app_module.create_app(_dev(state))
    ctx = app.state.app_context
    await account_fixture_guard(ctx.settings, app.state.account_fixture, ctx.oms_read_only_gate)
    FixtureClock(state).set(datetime.now(UTC) + timedelta(days=1))

    exchange = ctx.exchange_bybit
    calls = exchange.key_verification_calls("demo", UUID(int=1), uid="1", recv_window_ms=5000)
    await calls.aclose()

    found = [v for v in [*seen, *vars(exchange).values()] if isinstance(v, FixtureClock)]
    assert seen and not found
    assert seen[-1]() == pytest.approx(datetime.now(UTC).timestamp(), abs=60)
    assert not [name for name in dir(app.state.account_fixture) if "clock" in name]
