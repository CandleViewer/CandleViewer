"""Composition-root wiring (not a module) for the exposure read (E27-S04 B2a, #898).

M13 decides the exposure (`accounts.exposure`) and may import neither M2 nor M4 (C-3.1, C-3.2); M4
makes the signed calls. This glue binds them. Each key's read gets its own trading port from the
adapter (`exposure_port`), so two keys of one account never share a client: the port keeps one
client per account and closes it when another key of that account arrives. The key's positions
read and its open-orders read run at once, both on the `poll` lane, so the read never spends the
reserve that stops and cancels draw on (C-12.7). The port is closed when the read ends, cancelled
or not, within `CLOSE_BOUND_S`.

Errors: the port strips every failure of its cause (SR-E29-08), and a stripped timeout, reset or
M2 refusal no longer says what it was. So the port hands each call's failure to a hook first, and
the adapter names it there (`exposure_probe_error`: `probe_error` for an exchange error,
`vault_refused` when M2 refused to sign). A context variable set by each call routes the hook's
word to the call it belongs to, as the two calls share the key's port. A failure the hook did not
name (an answer the port could not read) is named from the error the port raised. The key fails
with the word that ranks first (`accounts.exposure.combine`): never exchange text, and the log
line carries the key id and the word only (SR-E27-08, C-12.6). Bound to the process environment
(C-2.11); only the real backend reads, and the fake one (dev/CI) has no read (C-13.5). Nothing
here does I/O until a read is asked for.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.consequences import ConsequenceRead, ConsequenceStores
from candleviewer.accounts.exposure import (
    EXCHANGE_ERROR,
    ExchangePosition,
    ExposureRead,
    KeyExposure,
    KeyReadFailed,
    combine,
)
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.profile_repository import ArmedRules
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.base.models import AccountRef, Order, Position
from candleviewer.observability import spawn, spawn_child

if TYPE_CHECKING:
    from candleviewer.app import AppContext

__all__ = [
    "CLOSE_BOUND_S",
    "ConsequencePorts",
    "ExposureVenue",
    "NoRunningAlgos",
    "PortReader",
    "wire_consequence_read",
    "wire_exposure_read",
]

#: The bound on closing one key's port after its read (its clients, never the shared transport).
CLOSE_BOUND_S: Final = 0.1
_SIDE: Final[Mapping[str | None, Literal["long", "short", "flat"]]] = {
    "buy": "long",
    "sell": "short",
    None: "flat",
}
#: The failures the port's hook named during the current call (one list per call's task).
_NAMED: ContextVar[list[KeyReadFailed] | None] = ContextVar("cv_exposure_named", default=None)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ReadPort(Protocol):
    """The trading port's reads this file uses."""

    async def positions(self, account: AccountRef) -> Sequence[Position]: ...
    async def open_orders(self, account: AccountRef) -> Sequence[Order]: ...
    async def aclose(self) -> None: ...


class ExposureVenue(Protocol):
    """The adapter surface the read uses (`AppContext.exchange_bybit`)."""

    def exposure_port(
        self,
        env: str,
        *,
        on_failure: Callable[[Exception], None],
        clock_offset_ms: Callable[[], int | None] | None = None,
    ) -> ReadPort: ...

    def exposure_probe_error(self, error: Exception) -> str | None: ...


def _failed(word: str, error: Exception) -> KeyReadFailed:
    """`word` with the exchange's code when it is an exchange error that sent one."""
    code = error.exchange_ret_code if isinstance(error, ExchangeError) else None
    return KeyReadFailed(word, code if word in EXCHANGE_ERROR else None)


def _position(row: Position) -> ExchangePosition:
    return ExchangePosition(
        symbol=row.symbol,
        position_idx=row.position_idx,
        side=_SIDE[row.side],
        size=row.qty,
        avg_price=row.avg_entry_price,
        mark_price=row.mark_price,
        liq_price=row.liq_price,
        leverage=row.leverage,
        unrealised_pnl=row.unrealised_pnl,
        take_profit=row.take_profit,
        stop_loss=row.stop_loss,
        trailing_stop=row.trailing_stop_distance,
        updated_at_us=row.updated_at,
    )


class PortReader:
    """`ExposureReader` over the adapter: one fresh port per key per read."""

    def __init__(
        self, venue: ExposureVenue, env: str, clock_offset_ms: Callable[[], int | None]
    ) -> None:
        self._venue, self._env, self._offset = venue, env, clock_offset_ms

    def _hook(self, raw: Exception) -> None:
        """The port's `on_failure`: name the raw failure while its cause is intact."""
        named = _NAMED.get()
        # Dropping the word when `_NAMED` is unset is deliberate and fail-safe: the fallback in
        # `_call` then names the failure `exchange_unknown` (502).
        word = self._venue.exposure_probe_error(raw)
        if named is not None and word is not None:
            named.append(_failed(word, raw))

    async def _call[T](self, call: Callable[[], Awaitable[T]]) -> T | KeyReadFailed:
        named: list[KeyReadFailed] = []
        token = _NAMED.set(named)
        try:
            return await call()
        except ExchangeError as error:
            if named:
                return named[-1]
            return _failed(self._venue.exposure_probe_error(error) or "exchange_unknown", error)
        finally:
            _NAMED.reset(token)

    async def read(self, account: ExchangeAccount, key_id: UUID) -> KeyExposure:
        if account.env.value != self._env:
            raise ValueError("the account belongs to another environment")
        ref = AccountRef.model_validate(
            {
                "account_id": AccountId(account.id),
                "uid": account.exchange_uid,
                "environment": self._env,
                "key_ref": str(key_id),
            }
        )
        port = self._venue.exposure_port(
            self._env, on_failure=self._hook, clock_offset_ms=self._offset
        )
        try:
            async with asyncio.TaskGroup() as group:
                held = spawn_child(
                    group, self._call(lambda: port.positions(ref)), name="exposure-positions"
                )
                working = spawn_child(
                    group, self._call(lambda: port.open_orders(ref)), name="exposure-orders"
                )
        finally:
            await _close(port, key_id)
        positions, orders = held.result(), working.result()
        if isinstance(positions, KeyReadFailed) or isinstance(orders, KeyReadFailed):
            failed = combine(got for got in (positions, orders) if isinstance(got, KeyReadFailed))
            word = failed.probe_error
            _log().info("exposure_key_read_failed", key_id=str(key_id), probe_error=word)
            raise KeyReadFailed(word, failed.ret_code)
        return KeyExposure(tuple(_position(row) for row in positions), len(orders))


#: Closes still running when their read was cancelled (held so none is collected mid-way). Each
#: entry is a close bounded by CLOSE_BOUND_S, at most one per key per read, so request
#: concurrency bounds the set; at loop teardown a still-running close is cancelled like any task.
_CLOSING: set[asyncio.Task[None]] = set()


async def _close_one(port: ReadPort, key_id: UUID) -> None:
    """Close `port` within `CLOSE_BOUND_S`; a slow or failed close is logged, never raised."""
    try:
        await asyncio.wait_for(port.aclose(), CLOSE_BOUND_S)
    except TimeoutError:
        _log().warning("exposure_port_close_slow", key_id=str(key_id))
    except Exception as fault:  # the read's result or cancel stands; the type name only
        _log().warning("exposure_port_close_failed", key_id=str(key_id), fault=type(fault).__name__)


async def _close(port: ReadPort, key_id: UUID) -> None:
    """Close the key's port, also while its read is being cancelled: the close runs shielded
    (a second cancel does not abandon it) and bounded by `CLOSE_BOUND_S`; a cancel is never
    swallowed, any other close fault is only logged."""
    closing = spawn(_close_one(port, key_id), name=f"exposure-close-{key_id}")
    _CLOSING.add(closing)
    closing.add_done_callback(_CLOSING.discard)
    await asyncio.shield(closing)


def wire_exposure_read(ctx: AppContext) -> ExposureRead | None:
    """The exposure read on the real backend, on the process environment; `None` on the fake
    one. Requests carry the exchange's clock once the ingestion clock guard has measured it."""
    settings = ctx.settings
    if settings.storage_backend != "real":
        return None
    env = settings.environment.value

    def offset_ms() -> int | None:
        """Exchange minus host clock, read per request: `None` until the guard measured it."""
        return ctx.ingestion.clock_offset_ms()

    venue: ExposureVenue = ctx.exchange_bybit
    return ExposureRead(PortReader(venue, env, offset_ms), env=env)


class NoRunningAlgos:
    """`RunningAlgos` until the emulated-algo supervisor lands (E33): none can run, so none is."""

    async def running(self, account_id: UUID) -> int:
        return 0


class ConsequencePorts(Protocol):
    """What the read takes of `profiles_wiring.ProfilesWiring`: its store and armed-rule read."""

    @property
    def accounts(self) -> ConsequenceStores: ...

    @property
    def rules(self) -> ArmedRules: ...


def wire_consequence_read(
    exposure: ExposureRead | None, profiles: ConsequencePorts | None, *, env: str
) -> ConsequenceRead | None:
    """The consequence read (E27-S04 B2b, #898) over the exposure read and the profile wiring's
    accounts store and armed-rule read (one pool), on the process environment; `None` without
    either (the fake backend: the route answers 503)."""
    if exposure is None or profiles is None:
        return None
    return ConsequenceRead(profiles.accounts, exposure, profiles.rules, NoRunningAlgos(), env=env)
