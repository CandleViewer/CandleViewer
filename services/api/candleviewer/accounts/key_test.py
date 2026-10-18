"""`testApiKey`, the on-demand test of one stored key, over ports (E27-T03 slice 2b6, #836).

An M13 flow like `key_import.py`: it imports no M2 or M4 module and adds no import edge (C-3.1,
C-3.2, C-3.4); `key_test_wiring` binds its ports. For the acting Owner (`Importer`):

1. The account and the key are read in the caller's owner scope (SR-051). An account of another
   environment is `not_found`, as a missing one is, and so is a key of another account (C-2.11, no
   existence oracle). Only an `active` or `rotating` key is signed with; any other is a `conflict`.
2. One test per key per minute (`Throttle`; the ticket's denial-of-service threat): a second is
   `rate_limited` with the seconds to wait. Nothing is probed for any refusal so far.
3. The REST half is the self-check's (`KeySelfCheck.test`, decision 11 on #836): the key's
   pipeline, and its verdict handled as the hourly pass handles one, so a failure latches the
   process read-only and force-disables the account at once, a pass refreshes the key's last pass,
   and `account.tested` names the Owner. A check with no verdict changes nothing and shows no
   verification (SR-E27-18): its `KeyProbeError` name and the exchange's code when it sent one. M2
   refusing to sign answers `kek_unavailable` or `exchange_unavailable` and gives the key's minute
   back, as nothing reached the exchange. So does a job with no egress IP configured, which signs
   and judges nothing, as its pass does then (`exchange_unavailable`).
4. With `include_ws`, the WebSocket half: the adapter's one-shot private `auth` (slice 2b5), only
   after a REST half that refused nothing, so a key a verdict refused is never signed with again
   (`verify()`'s order). It is diagnostic (ruling 11): it never enforces and never raises, and its
   failure only makes `passed` false.
5. Bounds (ticket performance notes): 5 s per signed call and 12 s for the REST half are the job's,
   and the WebSocket half gets what is left of 12 s from the test's start: with nothing left it
   is a `timeout` that opens nothing. The verdict's handling is never cut by them. Nothing here is
   on the order path.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.errors import (
    AccountNotFoundError,
    AccountScopeDeniedError,
    AccountsError,
)
from candleviewer.accounts.key_import import IO_TIMEOUT_S, Importer
from candleviewer.accounts.models import ExchangeAccount, KeyStatus
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.selfcheck import KEY_DEADLINE_S, NoEgressIp, Target
from candleviewer.accounts.verification import VerificationInconclusive, VerificationResult
from candleviewer.storage.repositories.accounts import OwnerScope

#: One test per key per this many seconds (E27-T03, #836).
WINDOW_S: Final = 60.0
#: The keys the throttle holds at most (C-2.18): far above the signable keys of an environment.
MAX_KEYS: Final = 256
CONFLICT, THROTTLED, STORE = "conflict", "rate_limited", "store_unavailable"
EXCHANGE: Final = "exchange_unavailable"
_SIGNABLE: Final = frozenset({KeyStatus.ACTIVE, KeyStatus.ROTATING})
#: M2's refusals to sign, by their class `code` (no M2 import, C-3.2), as the answer's codes.
_UNSIGNED: Final = {
    "kek_unavailable": "kek_unavailable",
    "credential_unavailable": EXCHANGE,
}
#: `KeyProbeError` (SR-E27-08), closed: a REST half without a verdict shows one of these.
PROBE_ERRORS: Final = frozenset(
    {
        "auth_error", "permission_denied", "ip_not_allowed", "clock_drift", "rate_limited",
        "service_unavailable", "transport_error", "timeout", "exchange_unknown",
    }
)  # fmt: skip
#: The pipeline's own no-verdict codes by name: an answer past the window, a stepped host clock.
_RENAMED: Final = {"probe_slow": "timeout", "probe_clock_step": "clock_drift"}
#: The exchange refusing the key (a verdict) by name; any other code (33004) is `exchange_unknown`.
_REFUSED: Final = {10003: "auth_error", 10005: "permission_denied", 10010: "ip_not_allowed"}


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class PrivateAuth(Protocol):
    """The adapter's one private-WS `auth` probe's result."""

    @property
    def ok(self) -> bool: ...
    @property
    def error(self) -> str | None: ...
    @property
    def latency_ms(self) -> int | None: ...


class SelfCheck(Protocol):
    """The job's on-demand entry (`KeySelfCheck.test`): the verdict and its calls' seconds, or
    `NoEgressIp` when it can judge no key."""

    async def test(
        self, target: Target, account: ExchangeAccount, now: datetime, actor: Mapping[str, object]
    ) -> tuple[VerificationResult, float]: ...


class KeyTestRefused(AccountsError):
    """A test that probed nothing, by its answer's problem code; `retry_after_s` when throttled."""

    def __init__(self, code: str, detail: str, retry_after_s: int | None = None) -> None:
        super().__init__(code)
        self.code, self.detail, self.retry_after_s = code, detail, retry_after_s


@dataclass(frozen=True, slots=True)
class Probe:
    """`KeyTestResult.rest` or `.websocket`; `ret_code` is the REST half's alone."""

    ok: bool
    latency_ms: int | None
    error: str | None
    ret_code: int | None = None


@dataclass(frozen=True, slots=True)
class KeyTested:
    """`KeyTestResult`: no `verdict` when the REST half reached none, no `websocket` when that
    half did not run."""

    checked_at: datetime
    rest: Probe
    verdict: VerificationResult | None
    websocket: Probe | None

    @property
    def passed(self) -> bool:
        """The verdict passed, the REST probe succeeded and, when it ran, the WebSocket `auth`."""
        socket = self.websocket is None or self.websocket.ok
        return self.verdict is not None and self.verdict.passed and self.rest.ok and socket


@dataclass(frozen=True, slots=True)
class _Key:
    """The stored key as the job's check reads it (`Target`)."""

    key_id: UUID
    read_only: bool
    verified_at: datetime


class Throttle:
    """One test per key per `window_s` in a bounded map (C-2.18): a key's entry ends with its
    window, and at most `cap` keys are held. A full map of open windows refuses a new key until
    the oldest ends, and never drops an open window, so no flood of tests reopens a key early."""

    def __init__(
        self, *, window_s: float = WINDOW_S, cap: int = MAX_KEYS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:  # fmt: skip
        self._window_s, self._cap, self._monotonic = window_s, cap, monotonic
        #: When each held key's window opened, oldest first.
        self._opened: dict[UUID, float] = {}

    def admit(self, key_id: UUID) -> int | None:
        """`None` when the key may be tested now (its window opens); else the seconds to wait."""
        now = self._monotonic()
        while self._opened and now - next(iter(self._opened.values())) >= self._window_s:
            del self._opened[next(iter(self._opened))]
        opened = self._opened.get(key_id)
        if opened is None and len(self._opened) >= self._cap:
            opened = next(iter(self._opened.values()))
        if opened is not None:
            return max(1, math.ceil(self._window_s - (now - opened)))
        self._opened[key_id] = now
        return None

    def release(self, key_id: UUID) -> None:
        """Give a key's window back: its test reached nothing at the exchange."""
        self._opened.pop(key_id, None)


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def _answered(verdict: VerificationResult, took: float) -> Probe:
    """A verdict's REST half, by the last call it made: a refusal by its `KeyProbeError` name, and
    none for a stored row M2 refused to sign with (SR-E27-14: no call was made)."""
    code = verdict.key_info_ret_code if verdict.probe_ret_code is None else verdict.probe_ret_code
    error = None if code in (0, None) else _REFUSED.get(code, "exchange_unknown")
    return Probe(code == 0, _ms(took), error, code)


def _unanswered(exc: Exception, took: float) -> Probe:
    """No verdict: its `KeyProbeError` name, and the exchange's code when it sent one."""
    if not isinstance(exc, VerificationInconclusive):  # the REST half's deadline
        return Probe(False, _ms(took), "timeout")
    name = _RENAMED.get(str(exc), str(exc))
    shown = name if name in PROBE_ERRORS else "exchange_unknown"
    return Probe(False, _ms(took), shown, exc.ret_code)


class KeyTest:
    """`testApiKey` for the process environment (module docstring)."""

    def __init__(
        self, accounts: AccountsRepository, job: SelfCheck,
        websocket: Callable[[UUID], Awaitable[PrivateAuth]], *, env: str,
        clock: Callable[[], datetime], monotonic: Callable[[], float] = time.monotonic,
        deadline_s: float = KEY_DEADLINE_S, timeout_s: float = IO_TIMEOUT_S,
    ) -> None:  # fmt: skip
        self._accounts, self._job, self._websocket, self._env = accounts, job, websocket, env
        self._clock, self._monotonic = clock, monotonic
        self._deadline_s, self._timeout_s = deadline_s, timeout_s
        self.throttle = Throttle(monotonic=monotonic)

    async def run(
        self, account_id: UUID, key_id: UUID, actor: Importer, *, include_ws: bool = True
    ) -> KeyTested:
        """The test's result, or its refusal with nothing probed (`KeyTestRefused`,
        `AccountNotFoundError`, `AccountScopeDeniedError`). A refusal after the throttle gives
        the key's minute back."""
        scope = OwnerScope(actor.user_id)
        account = await self._read(self._accounts.get_account(scope, account_id))
        if account.env.value != self._env:  # never signed for on this environment's host
            raise AccountNotFoundError("account")
        key = await self._read(self._accounts.get_key(scope, account.id, key_id))
        if key.status not in _SIGNABLE:
            raise KeyTestRefused(CONFLICT, f"The key is {key.status}, so it cannot be tested.")
        if (wait := self.throttle.admit(key.id)) is not None:
            text = f"One test per key per minute; retry in {wait} s."
            raise KeyTestRefused(THROTTLED, text, wait)
        now, started = self._clock(), self._monotonic()
        who = {
            "actor_label": f"user:{actor.role}", "actor_user_id": actor.user_id,
            "actor_ip": actor.ip, "request_id": actor.request_id,
        }  # fmt: skip
        target = _Key(key.id, key.read_only, key.permission_snapshot_at)
        verdict: VerificationResult | None = None
        try:
            verdict, took = await self._job.test(target, account, now, who)
            rest = _answered(verdict, took)
        except (VerificationInconclusive, TimeoutError) as exc:  # no verdict: nothing changed
            rest = _unanswered(exc, self._monotonic() - started)
        except NoEgressIp:  # the job judges no key without one, as its pass (decision 11)
            self.throttle.release(key.id)
            text = "No egress IP is configured, so the key could not be tested."
            raise KeyTestRefused(EXCHANGE, text) from None
        except Exception as exc:  # M2 refusing to sign, by its class code; anything else goes on
            if (code := _UNSIGNED.get(str(getattr(type(exc), "code", "")))) is None:
                raise
            self.throttle.release(key.id)
            text = "Signing is unavailable, so the key could not be tested."
            raise KeyTestRefused(code, text) from None
        socket = None
        if include_ws and (verdict is None or verdict.passed):
            socket = await self._socket(key.id, started)
        return KeyTested(now, rest, verdict, socket)

    async def _socket(self, key_id: UUID, started: float) -> Probe:
        """The WebSocket half within what is left of the deadline. Diagnostic: whatever ends it
        is its result, never raised (a cancellation still propagates). With nothing left the port
        is never called: its probe spends one of the deployment's opens first (SR-E27-05)."""
        left = started + self._deadline_s - self._monotonic()
        if left <= 0:
            return Probe(False, None, "timeout")
        try:
            async with asyncio.timeout(left):
                auth = await self._websocket(key_id)
        except TimeoutError:
            return Probe(False, None, "timeout")
        except Exception as exc:  # M2 refusing the `auth` signature, say: logged by its class
            _log().warning("key_test_ws_failed", key_id=str(key_id), error=type(exc).__name__)
            return Probe(False, None, "auth_error")
        return Probe(auth.ok, auth.latency_ms, auth.error)

    async def _read[T](self, step: Awaitable[T]) -> T:
        """One store read, bounded. A missing or out-of-scope row propagates; an outage or a
        timeout is `store_unavailable`, logged by its class, never its text."""
        try:
            async with asyncio.timeout(self._timeout_s):
                return await step
        except (AccountNotFoundError, AccountScopeDeniedError):
            raise
        except Exception as exc:  # TimeoutError included; cancellation propagates
            _log().error("key_test_store_failed", error=type(exc).__name__)
            raise KeyTestRefused(STORE, "The relational store is unavailable.") from None
