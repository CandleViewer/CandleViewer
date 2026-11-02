"""#5282: the wallet reconciler's REST read is the exchange's on the real backend. The adapter
(`wallet_rest_wiring.py`) is driven over the real trading port on a scripted transport, whose
replies are the recorded `key_verification` captures (`wallet_balance.json`, `error_*.json`); a
test input derived from one says so. No network, no wall-clock wait (C-13.5)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

import candleviewer.app as appmod
from candleviewer.account_health_wiring import UnavailableWalletRest
from candleviewer.accounts.health import HealthState
from candleviewer.accounts.verification import KeyRefused, Refusal
from candleviewer.accounts.wallet import WalletUnavailable
from candleviewer.exchange.base.errors import AuthError, TransportError
from candleviewer.exchange.base.models import AccountRef, Wallet
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.settings import Environment, Settings
from candleviewer.wallet_rest_wiring import AccountRefs, ExchangeWalletRest
from tests.unit.accounts._fakes import ACC, ACC_B, key_of, key_row
from tests.unit.accounts._runtime_rig import Rig
from tests.unit.exchange.bybit._trading import Venue, make_port
from tests.unit.test_account_health_wiring import _real, stored

__all__ = ["stored"]  # the fixture, re-exported for the composition tests below

FIXTURES = Path(__file__).parents[1] / "fixtures" / "key_verification"
WALLET_PATH = "/v5/account/wallet-balance"
ENV = "demo"


def _capture(name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return body


WALLET = _capture("wallet_balance.json")
#: The envelope's clock, as the datetime a clock reading it is.
AT = datetime.fromtimestamp(WALLET["time"] / 1000, tz=UTC)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return 0.0


class _Venue:
    """The adapter surface over the real trading port: one port per `exposure_port` call, which
    the test can count, and the adapter's own `exposure_probe_error`."""

    def __init__(self, script: Venue) -> None:
        self.script = script
        self.ports: list[Any] = []
        self.closed = 0
        self.envs: list[str] = []
        self.offsets: list[Any] = []

    def exposure_port(self, env: str, *, on_failure: Any, clock_offset_ms: Any = None) -> Any:
        self.envs.append(env)
        self.offsets.append(clock_offset_ms)
        port = make_port(self.script, environment=env)
        self.ports.append(port)
        real_close = port.aclose

        async def aclose() -> None:
            self.closed += 1
            await real_close()

        port.aclose = aclose
        del on_failure  # the real port calls it; the adapter's own fallback is covered too
        return port

    def exposure_probe_error(self, error: Exception) -> str | None:
        return ExchangeBybitService.exposure_probe_error(error)


def _adapter(script: Venue, *, now: datetime = AT) -> tuple[ExchangeWalletRest, _Venue]:
    venue = _Venue(script)
    adapter = ExchangeWalletRest(venue, ENV, lambda: None, clock=_Clock(now))
    adapter.refs.observe([key_row(ACC, env=ENV)])
    return adapter, venue


async def test_the_recorded_wallet_balance_maps_to_the_usdt_snapshot_on_the_poll_lane() -> None:
    script = Venue().on(WALLET_PATH, WALLET)
    adapter, venue = _adapter(script)

    snapshot = await adapter.wallet(ACC)

    assert (snapshot.coin, snapshot.equity, snapshot.wallet_balance) == (
        "USDT",
        Decimal("10000.00"),
        Decimal("10000.00"),
    )
    assert snapshot.available_balance == Decimal("10000.00")
    assert (snapshot.account_im_rate, snapshot.account_mm_rate) == (Decimal(0), Decimal(0))
    assert snapshot.updated_at == AT
    assert script.paths() == [WALLET_PATH] and script.queries() == [
        {"accountType": "UNIFIED", "coin": "USDT"}
    ]
    assert venue.envs == [ENV] and venue.closed == 1  # env-bound, and the port closed


async def test_the_read_signs_for_the_cached_uid_and_the_active_key_only() -> None:
    adapter, venue = _adapter(Venue().on(WALLET_PATH, WALLET))
    rows = [key_row(ACC, env=ENV), key_row(ACC_B, env=ENV, key=key_of(ACC_B))]
    adapter.observe(rows)
    seen: list[AccountRef] = []
    original = venue.exposure_port

    def spy(env: str, **kw: Any) -> Any:
        port = original(env, **kw)
        real = port.wallet

        async def wallet(account: AccountRef) -> Wallet:
            seen.append(account)
            return await real(account)

        port.wallet = wallet
        return port

    venue.exposure_port = spy  # type: ignore[method-assign]
    await adapter.wallet(ACC_B)
    [ref] = seen
    assert (ref.account_id, ref.uid, ref.key_ref, ref.environment) == (
        ACC_B,
        "1000001",
        str(key_of(ACC_B)),
        ENV,
    )


async def test_an_account_with_no_active_key_is_unavailable_and_sends_nothing() -> None:
    script = Venue()
    adapter, venue = _adapter(script)
    rotating = key_row(ACC_B, env=ENV)
    object.__setattr__(rotating, "status", "rotating")
    adapter.observe([rotating, key_row(UUID(int=9), env="live")])  # a foreign env is dropped
    for account in (ACC, ACC_B, UUID(int=9)):
        with pytest.raises(WalletUnavailable):
            await adapter.wallet(account)
    assert venue.ports == [] and script.sent == []


async def test_a_port_that_cannot_be_built_is_unavailable_and_logs_the_type_only() -> None:
    adapter, venue = _adapter(Venue())

    def refuse(env: str, **kw: Any) -> Any:
        raise ValueError("testnet has no credentials wired: secret-ish text")

    venue.exposure_port = refuse  # type: ignore[method-assign]
    with capture_logs() as logs, pytest.raises(WalletUnavailable):
        await adapter.wallet(ACC)
    assert [e.get("fault") for e in logs if e["event"] == "wallet_rest_failed"] == ["ValueError"]
    assert "secret-ish" not in repr(logs)


async def test_another_environments_rows_are_never_cached() -> None:
    refs = AccountRefs()
    adapter = ExchangeWalletRest(_Venue(Venue()), ENV, lambda: None, refs)
    adapter.observe([key_row(ACC, env="live")])
    assert refs.get(ACC) is None


@pytest.mark.parametrize(
    ("capture", "reason", "code"),
    [
        ("error_10010.json", Refusal.IP_NOT_ALLOWED, 10010),
        ("error_10010.json", Refusal.PERMISSION_DENIED, 10005),  # the capture, its code changed
    ],
    ids=["ip_not_allowed", "permission_denied"],
)
async def test_a_verdict_about_the_key_is_a_refusal_with_the_venues_code(
    capture: str, reason: Refusal, code: int
) -> None:
    answer = {**_capture(capture), "retCode": code}
    adapter, venue = _adapter(Venue().on(WALLET_PATH, answer))
    with pytest.raises(KeyRefused) as refused:
        await adapter.wallet(ACC)
    assert (refused.value.reason, refused.value.code) == (reason, code)
    assert venue.closed == 1


@pytest.mark.parametrize("reason", list(Refusal))
async def test_every_refusal_word_the_vocabulary_names_maps_one_to_one(reason: Refusal) -> None:
    """`unknown_key` and `key_expired` are `Refusal` values and `KeyProbeError` words, but the
    adapter's `probe_error` table gives neither today (10003 reads `auth_error`, 33004 reads
    `exchange_unknown`): the adapter maps whichever word the venue names, and the table is the
    adapter's to widen (reported on #5282)."""
    adapter, venue = _adapter(Venue().on(WALLET_PATH, _capture("error_10010.json")))
    venue.exposure_probe_error = lambda _error: reason.value  # type: ignore[method-assign]
    with pytest.raises(KeyRefused) as refused:
        await adapter.wallet(ACC)
    assert refused.value.reason is reason and refused.value.code == 10010


@pytest.mark.parametrize("code", [10003, 10004, 10002, 10006, 10016, 33004, 99999])
async def test_any_other_exchange_failure_is_unavailable_and_logs_the_word_alone(
    code: int,
) -> None:
    answer = {**_capture("error_10010.json"), "retCode": code, "retMsg": "echo SECRET-TEXT"}
    adapter, venue = _adapter(Venue().on(WALLET_PATH, answer))
    with capture_logs() as logs, pytest.raises(WalletUnavailable) as caught:
        await adapter.wallet(ACC)
    assert "SECRET-TEXT" not in repr(caught.value) + repr(logs)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert venue.closed == 1


async def test_a_transport_failure_is_unavailable_and_names_its_type_only() -> None:
    adapter, venue = _adapter(Venue())  # no scripted path: the transport fails the call
    original = venue.exposure_port

    def broken(env: str, **kw: Any) -> Any:
        port = original(env, **kw)

        async def wallet(_account: AccountRef) -> Wallet:
            raise TransportError("connection reset by 10.0.0.1 key=abc")

        port.wallet = wallet
        return port

    venue.exposure_port = broken  # type: ignore[method-assign]
    with capture_logs() as logs, pytest.raises(WalletUnavailable):
        await adapter.wallet(ACC)
    assert "abc" not in repr(logs) and venue.closed == 1


async def test_a_wallet_dated_ahead_of_the_clock_is_unavailable() -> None:
    adapter, _ = _adapter(Venue().on(WALLET_PATH, WALLET), now=AT - timedelta(seconds=6))
    with pytest.raises(WalletUnavailable, match="ahead"):
        await adapter.wallet(ACC)
    ok, _ = _adapter(Venue().on(WALLET_PATH, WALLET), now=AT - timedelta(seconds=5))
    assert (await ok.wallet(ACC)).updated_at == AT  # exactly the skew allowed


async def test_a_wallet_with_no_usdt_row_is_unavailable() -> None:
    row = WALLET["result"]["list"][0]
    body = {**WALLET, "result": {"list": [{**row, "coin": [{**row["coin"][0], "coin": "BTC"}]}]}}
    adapter, venue = _adapter(Venue().on(WALLET_PATH, body))
    with pytest.raises(WalletUnavailable):
        await adapter.wallet(ACC)
    assert venue.closed == 1


async def test_a_wallet_whose_figures_fail_validation_logs_the_type_never_the_figures() -> None:
    row = WALLET["result"]["list"][0]
    huge = {**row, "totalEquity": "1" + "0" * 40, "coin": [{**row["coin"][0], "equity": "1e999"}]}
    adapter, _ = _adapter(Venue().on(WALLET_PATH, {**WALLET, "result": {"list": [huge]}}))
    with capture_logs() as logs, pytest.raises(WalletUnavailable):
        await adapter.wallet(ACC)
    assert "999" not in repr(logs)


async def test_the_failure_the_port_names_to_its_hook_decides_when_it_strips_the_cause() -> None:
    adapter, venue = _adapter(Venue())
    original = venue.exposure_port

    def stripping(env: str, *, on_failure: Any, **kw: Any) -> Any:
        port = original(env, on_failure=on_failure, **kw)

        async def wallet(_account: AccountRef) -> Wallet:
            raw = AuthError("x", exchange_ret_code=10010)
            on_failure(raw)  # the hook sees the cause intact ...
            raise TransportError("stripped")  # ... the port raises it without

        port.wallet = wallet
        return port

    venue.exposure_port = stripping  # type: ignore[method-assign]
    with pytest.raises(KeyRefused) as refused:
        await adapter.wallet(ACC)
    assert refused.value.reason is Refusal.IP_NOT_ALLOWED


async def test_a_cancelled_read_propagates_and_still_closes_the_port() -> None:
    adapter, venue = _adapter(Venue())
    original = venue.exposure_port
    started = asyncio.Event()

    def hanging(env: str, **kw: Any) -> Any:
        port = original(env, **kw)

        async def wallet(_account: AccountRef) -> Wallet:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        port.wallet = wallet
        return port

    venue.exposure_port = hanging  # type: ignore[method-assign]
    task = asyncio.create_task(adapter.wallet(ACC))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert venue.closed == 1


async def test_a_close_that_hangs_is_cut_off_and_does_not_fail_the_read() -> None:
    adapter, venue = _adapter(Venue().on(WALLET_PATH, WALLET))
    original = venue.exposure_port

    def slow(env: str, **kw: Any) -> Any:
        port = original(env, **kw)

        async def aclose() -> None:
            await asyncio.Event().wait()

        port.aclose = aclose
        return port

    venue.exposure_port = slow  # type: ignore[method-assign]
    with capture_logs() as logs:
        assert (await adapter.wallet(ACC)).coin == "USDT"
    assert [e["event"] for e in logs if e["event"].startswith("wallet_rest")] == [
        "wallet_rest_close_slow"
    ]


# -- through the reconciler on the fake clock ----------------------------------------------------


async def test_the_reconciler_reads_each_due_account_once_then_again_after_the_next_period() -> (
    None
):
    script = Venue().on(WALLET_PATH, WALLET)
    venue = _Venue(script)
    adapter = ExchangeWalletRest(venue, ENV, lambda: None, clock=_Clock(AT))
    adapter.observe([key_row(ACC, env=ENV)])
    rig = Rig(rest_port=adapter)
    await rig.boot()
    await rig.run(9.5)
    assert script.paths() == []  # nothing before the first period: a down account (no socket)
    # polls every `ws_down_poll_s` (10 s), a healthy one every `reconcile_s` (60 s)
    await rig.run(0.5)
    assert script.paths() == [WALLET_PATH]  # exactly one, for the one due account
    await rig.run(10)
    assert script.paths() == [WALLET_PATH] * 2  # and another after the next period
    assert venue.closed == 2
    await rig.close()


async def test_a_good_wallet_read_with_the_socket_down_makes_the_account_degraded_rest_only() -> (
    None
):
    adapter, _ = _adapter(Venue().on(WALLET_PATH, WALLET))
    rig = Rig(rest_port=adapter)
    await rig.boot()
    await rig.run(10)
    view = rig.runtime.monitor.view(ACC)
    await rig.close()
    assert view is not None
    assert (view.state, view.reason, view.rest_only) == (HealthState.DEGRADED, "rest_only", True)


# -- the composition -----------------------------------------------------------------------------


async def test_the_real_backend_binds_the_exchange_wallet_read_not_the_stand_in(
    stored: Any,
) -> None:
    runtime = appmod.create_app(_real()).state.account_health
    port = runtime._reconciler._rest
    assert isinstance(port, ExchangeWalletRest) and not isinstance(port, UnavailableWalletRest)
    stored.rows = [key_row(ACC, env="testnet")]
    await runtime.refresh_tracking()  # the tracking pass feeds the ref: no read of its own
    assert port.refs.get(ACC) == ("1000001", key_of(ACC))


def test_the_fake_backend_keeps_the_stand_in() -> None:
    runtime = appmod.create_app(Settings(environment=Environment.TESTNET)).state.account_health
    assert isinstance(runtime._reconciler._rest, UnavailableWalletRest)
