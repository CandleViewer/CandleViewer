"""E27-T03 (#836): the stored-key self-check's composition-root wiring.

The error table runs on M4's own classifier and `map_ret_code`, with exchange text in every
message so a leak would show; `respx` answers for every host. The skewed venue refuses, as the
exchange does, a request stamped 1 s or more ahead of its clock (10002, the corpus reply). No
network, no database.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
import respx
from pydantic import SecretStr

from candleviewer import key_selfcheck_wiring as wiring
from candleviewer.accounts.models import AccountKind, ExchangeAccount, ExchangeEnv
from candleviewer.accounts.service import AccountsService
from candleviewer.accounts.verification import (
    KeyRefused,
    Refusal,
    VerificationInconclusive,
    VerificationResult,
    VerificationWarning,
    verify,
)
from candleviewer.app import AppContext
from candleviewer.exchange.base.errors import ExchangeError, TransportError, UnknownStateError
from candleviewer.exchange.bybit.key_info import KEY_INFO_PATH, PROBE_PATH
from candleviewer.exchange.bybit.key_verify import CALL_TIMEOUT_S
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.settings import Environment, Settings
from tests._corpus import rest
from tests._signing import Call, fake_capability

FIXTURES = Path(__file__).parents[1] / "fixtures" / "key_verification"
ROOT = Path(__file__).resolve().parents[4]
HOSTS = ("api.bybit.com", "api-demo.bybit.com", "api-testnet.bybit.com")
KEY, TEXT = UUID(int=11), "exchange text that must never be echoed"
NOW, EGRESS, SKEW_MS = datetime(2026, 10, 15, 9, tzinfo=UTC), "203.0.113.7", 12_000
ACCOUNT = ExchangeAccount(
    id=UUID(int=1), env=ExchangeEnv.DEMO, kind=AccountKind.MAIN, exchange_uid="1000001",
    label="fx-demo", created_at=NOW, updated_at=NOW,
)  # fmt: skip


class Venue:
    """One key's adapter calls: raise `error`, or hang."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error, self.closed = error, False

    async def key_info(self) -> Any:
        if self.error is None:
            await asyncio.Event().wait()
        raise cast(BaseException, self.error)

    probe = key_info

    async def aclose(self) -> None:
        self.closed = True


def ctx(
    signed: list[Call] | None = None,
    clock: Callable[[], int | None] = lambda: None,  # the guard's offset: unmeasured
    **settings: Any,
) -> Any:
    return SimpleNamespace(
        settings=Settings(questdb_pg_password=SecretStr("not-the-dev-default"), **settings),
        exchange_bybit=ExchangeBybitService(credentials=fake_capability("test-key", signed)),
        oms_read_only_gate=ReadOnlyGate(),
        accounts=AccountsService(),
        ingestion=SimpleNamespace(clock_offset_ms=clock),
    )


async def judge(
    error: BaseException | None, call: str = "key_info", *, bound_s: float | None = None
) -> BaseException:
    venue, exchange = Venue(error), ExchangeBybitService()
    if bound_s is not None:
        exchange.key_call_timeout_s = bound_s
    calls = wiring.JudgedCalls(exchange, cast(Any, venue))
    with pytest.raises((KeyRefused, VerificationInconclusive)) as caught:
        await getattr(calls, call)()
    await calls.aclose()
    assert venue.closed  # the adapter's client is closed through the translation
    return caught.value


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        (10003, Refusal.UNKNOWN_KEY),
        (10005, Refusal.PERMISSION_DENIED),
        (10010, Refusal.IP_NOT_ALLOWED),
        (33004, Refusal.KEY_EXPIRED),
    ],
)
@pytest.mark.parametrize("call", ["key_info", "probe"])
async def test_a_refusal_about_the_key_is_a_verdict(code: int, reason: Refusal, call: str) -> None:
    refused = await judge(map_ret_code(code, TEXT), call)
    assert isinstance(refused, KeyRefused) and (refused.reason, refused.code) == (reason, code)
    assert (str(refused), refused.__cause__, refused.__suppress_context__) == (reason, None, True)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (map_ret_code(10004, TEXT), "10004"),
        (map_ret_code(10002, TEXT), "10002"),
        (map_ret_code(10018, TEXT), "10018"),
        (map_ret_code(10006, TEXT), "10006"),
        (TransportError(f"HTTP 503 {TEXT}"), "transport_error"),
        (UnknownStateError(f"malformed {TEXT}"), "unknown_state"),
        (ExchangeError(TEXT), "exchange_unknown"),
        (None, "timeout"),
    ],
    ids=["10004", "10002", "10018", "10006", "5xx", "malformed", "untyped", "timeout"],
)
async def test_any_other_error_is_inconclusive_with_a_code_only(
    error: ExchangeError | None, code: str
) -> None:
    inconclusive = await judge(error, bound_s=0.0)  # the adapter's bound cuts the hang at once
    assert isinstance(inconclusive, VerificationInconclusive) and str(inconclusive) == code
    assert inconclusive.__cause__ is None and inconclusive.__suppress_context__


def test_the_fake_backend_wires_no_self_check() -> None:
    fake = ctx()
    assert wiring.wire_key_selfcheck(cast(AppContext, fake), cast(Any, None)) is None
    assert fake.accounts._selfcheck is None


def test_the_real_backend_attaches_a_self_check_bound_to_the_process_environment() -> None:
    real = ctx(
        storage_backend="real", environment=Environment.TESTNET, egress_ip="203.0.113.7",
        key_selfcheck_interval_s=600.0, recv_window_ms=4000,
    )  # fmt: skip
    audit = object()
    check = wiring.wire_key_selfcheck(cast(AppContext, real), cast(Any, audit))
    assert check is not None and real.accounts._selfcheck is check
    store: Any = check._store
    assert (check._env, store._env, check._interval_s) == ("testnet", "testnet", 600.0)
    assert (check._gate, check._audit) == (real.oms_read_only_gate, audit)
    assert (check._policy.egress_ip, check._policy.recv_window_ms) == ("203.0.113.7", 4000)
    assert real.accounts._release == store._relational.dispose  # its pool is freed at stop()


def test_each_call_is_bounded_by_the_adapters_own_per_call_timeout() -> None:
    assert ExchangeBybitService().key_call_timeout_s == CALL_TIMEOUT_S == 5.0
    assert not hasattr(wiring, "CALL_TIMEOUT_S")  # read from the adapter, never a second copy


def test_the_wiring_names_no_exchange_venue() -> None:
    """C-2.2: `cv-adapter-isolation` (a blocking Semgrep rule) flags any venue name outside
    `exchange/bybit/`, an import included; the wiring reads the bound from the adapter instead."""
    rule = (ROOT / ".semgrep" / "cv-adapter-isolation.yml").read_text(encoding="utf-8")
    found = re.search(r"^\s*pattern-regex:\s*'([^']+)'", rule, re.MULTILINE)
    assert found is not None, "cv-adapter-isolation no longer declares a quoted `pattern-regex`"
    source = Path(wiring.__file__).read_text(encoding="utf-8")
    assert re.findall(found.group(1), source) == []


@pytest.fixture
def venue() -> Iterator[respx.MockRouter]:
    reply = json.loads((FIXTURES / "key_info_trade.json").read_text(encoding="utf-8"))
    with respx.mock(assert_all_called=False) as router:
        for host in HOSTS:
            router.get(f"https://{host}{KEY_INFO_PATH}").respond(json=reply)
            router.get(f"https://{host}{PROBE_PATH}").respond(json={"retCode": 10003})
        yield router


@pytest.mark.parametrize(
    ("env", "host"), [(Environment.DEMO, HOSTS[1]), (Environment.LIVE, HOSTS[0])]
)
async def test_the_wired_calls_sign_and_send_on_the_process_environment_only(
    venue: respx.MockRouter, env: Environment, host: str
) -> None:
    signed: list[Call] = []
    check = wiring.wire_key_selfcheck(
        cast(AppContext, ctx(signed, storage_backend="real", environment=env)), cast(Any, None)
    )
    assert check is not None
    calls = check._calls(KEY, "1000001")
    assert (await calls.key_info()).uid == "1000001"
    with pytest.raises(KeyRefused):  # 10003 on the probe: this key is unknown on this host
        await calls.probe()
    await calls.aclose()
    assert [(c.request.url.host, c.request.url.path) for c in venue.calls] == [
        (host, KEY_INFO_PATH), (host, PROBE_PATH),
    ]  # fmt: skip
    assert [(key, purpose) for key, _, purpose in signed] == [(KEY, "key_verify")] * 2


@pytest.fixture
def skewed() -> Iterator[respx.MockRouter]:
    """The demo host on an exchange clock `SKEW_MS` behind the host's."""
    info, balance = (
        json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        for name in ("key_info_trade.json", "wallet_balance.json")
    )

    def answer(request: httpx.Request) -> httpx.Response:
        server = int(time.time() * 1000) - SKEW_MS
        if int(request.headers["X-BAPI-TIMESTAMP"]) >= server + 1000:
            return httpx.Response(200, json=rest("rest/error_10002.json"))
        body = info if request.url.path == KEY_INFO_PATH else balance
        return httpx.Response(200, json={**body, "time": server})

    with respx.mock(assert_all_called=False) as router:
        for path in (KEY_INFO_PATH, PROBE_PATH):
            router.get(f"https://{HOSTS[1]}{path}").mock(side_effect=answer)
        yield router


async def verify_skewed(measured: int | None) -> VerificationResult:
    """The wired calls through the key-import pipeline, the guard's offset `measured`."""
    real = ctx(clock=lambda: measured, storage_backend="real", egress_ip=EGRESS)
    check = wiring.wire_key_selfcheck(cast(AppContext, real), cast(Any, None))
    assert check is not None
    calls = check._calls(KEY, ACCOUNT.exchange_uid)
    try:
        return await verify(
            ACCOUNT, read_only=False, key_info=calls.key_info, probe=calls.probe,
            policy=check._policy, now=NOW,
        )  # fmt: skip
    finally:
        await calls.aclose()


async def test_a_host_clock_12_s_ahead_shows_in_the_offset_with_a_warning_once_measured(
    skewed: respx.MockRouter,
) -> None:
    result = await verify_skewed(-SKEW_MS)
    assert result.passed and VerificationWarning.CLOCK_OFFSET in result.warnings
    offset = result.clock_offset_ms  # the probe's own latency (at most 5 s) blurs it by half
    assert offset is not None and -SKEW_MS - 2_500 <= offset <= -SKEW_MS + 2_500


async def test_an_unmeasured_skew_is_the_venues_clock_refusal_never_a_verdict(
    skewed: respx.MockRouter,
) -> None:
    with pytest.raises(VerificationInconclusive, match=r"^10002$"):
        await verify_skewed(None)
    assert [c.request.url.path for c in skewed.calls] == [KEY_INFO_PATH] * 2  # one re-sign
