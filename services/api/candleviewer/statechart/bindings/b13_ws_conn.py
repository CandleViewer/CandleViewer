"""candleviewer.statechart.bindings.b13_ws_conn — MachineLogic stubs for B13 `ws_conn`
(E50-S02). Chart: `machines/B13.ws_conn.machine.json`.

E08-T04 wires these names to the ingestion `ConnectionManager` through a
per-connection runtime registered under `context["input"]["conn_key"]`; with no
runtime registered guards deny and actions/services are no-ops (A6).
Names are fixed by the chart contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


class WsConnRuntime(Protocol):
    """Transport-side hooks the B13 chart drives. Implemented by
    `candleviewer.ingestion.connection.ConnectionManager` (the statechart
    package never imports ingestion); registered per connection under the
    `conn_key` carried in the chart context."""

    attempt: int

    def is_private(self) -> bool: ...
    def budget_exhausted(self) -> bool: ...
    async def open_socket(self) -> None: ...
    async def authenticate(self) -> None: ...
    async def subscribe(self) -> None: ...
    async def close_socket(self) -> None: ...
    async def teardown_session(self) -> None: ...
    def start_session(self, interp: Any) -> None: ...
    def schedule_backoff(self, interp: Any) -> None: ...
    def schedule_budget_recheck(self, interp: Any) -> None: ...
    async def emit_health(self, state: str) -> None: ...
    def reset_attempt(self) -> None: ...
    def bump_attempt(self) -> None: ...


_RUNTIMES: dict[str, WsConnRuntime] = {}


def register_runtime(conn_key: str, runtime: WsConnRuntime) -> None:
    _RUNTIMES[conn_key] = runtime


def unregister_runtime(conn_key: str) -> None:
    _RUNTIMES.pop(conn_key, None)


def _rt(context: dict[str, Any]) -> WsConnRuntime | None:
    inp = context.get("input")
    key = inp.get("conn_key") if isinstance(inp, dict) else context.get("conn_key")
    return _RUNTIMES.get(str(key or ""))


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


async def bump_attempt(interp: Any, context: dict[str, Any], *_a: object) -> None:
    context["attempt"] = int(context.get("attempt", 0)) + 1
    if (rt := _rt(context)) is not None:
        rt.bump_attempt()


async def reset_backoff(interp: Any, context: dict[str, Any], *_a: object) -> None:
    context["attempt"] = 0
    if (rt := _rt(context)) is not None:
        rt.reset_attempt()


async def emit_feed_healthy(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        await rt.emit_health("healthy")


async def emit_feed_degraded(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        await rt.emit_health("degraded")


async def raise_conn_budget_alert(interp: Any, context: dict[str, Any], *_a: object) -> None:
    """Entering `budget_blocked`: a reconnect storm hit the connection-rate
    budget — report the feed as `degraded` (E08-T04 AC "reconnect storms")."""
    if (rt := _rt(context)) is not None:
        await rt.emit_health("degraded")


async def compute_jittered_backoff(interp: Any, context: dict[str, Any], *_a: object) -> None:
    """Entering `backing_off`: tear the dead session down (socket + tasks)."""
    if (rt := _rt(context)) is not None:
        await rt.teardown_session()


async def schedule_backoff_deadline(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        rt.schedule_backoff(interp)


async def schedule_budget_recheck(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        rt.schedule_budget_recheck(interp)


async def record_subscribed(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        rt.start_session(interp)


def is_private(context: dict[str, Any], *_a: object) -> bool:
    rt = _rt(context)
    return bool(rt.is_private()) if rt is not None else False


def connection_budget_exhausted(context: dict[str, Any], *_a: object) -> bool:
    rt = _rt(context)
    return bool(rt.budget_exhausted()) if rt is not None else False


async def open_socket(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        await rt.open_socket()


async def ws_auth(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        await rt.authenticate()


async def subscribe_in_batches(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        await rt.subscribe()


async def close_socket(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        await rt.close_socket()


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "arm_pong_deadline": _noop_action,  # pong liveness is the manager's ping task
    "audit_kill": _noop_action,
    "bump_attempt": bump_attempt,
    "compute_jittered_backoff": compute_jittered_backoff,
    "emit_feed_degraded": emit_feed_degraded,
    "emit_feed_healthy": emit_feed_healthy,
    "notify_dependents_degraded": _noop_action,  # dependents consume FeedHealthEvent on the bus
    "raise_conn_budget_alert": raise_conn_budget_alert,
    "rearm_pong_deadline": _noop_action,
    "record_auth_error": _noop_action,
    "record_conn_error": _noop_action,
    "record_pong_timeout": _noop_action,
    "record_staleness": _noop_action,
    "record_sub_error": _noop_action,
    "record_subscribed": record_subscribed,
    "reset_backoff": reset_backoff,
    "schedule_backoff_deadline": schedule_backoff_deadline,
    "schedule_budget_recheck": schedule_budget_recheck,
    "set_pending_topics": _noop_action,
    "stamp_pong": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "connection_budget_exhausted": connection_budget_exhausted,
    "is_private": is_private,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "close_socket": close_socket,
    "open_socket": open_socket,
    "subscribe_in_batches": subscribe_in_batches,
    "ws_auth": ws_auth,
}

register_binding_module("ws_conn", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    "ws_conn",
    {
        "BACKOFF_DUE": _ANY_PAYLOAD,
        "BUDGET_RECHECK": _ANY_PAYLOAD,
        "CONNECT": _ANY_PAYLOAD,
        "KILL": _ANY_PAYLOAD,
        "PONG": _ANY_PAYLOAD,
        "PONG_DEADLINE": _ANY_PAYLOAD,
        "SHUTDOWN": _ANY_PAYLOAD,
        "SOCKET_CLOSED": _ANY_PAYLOAD,
        "TOPICS_CHANGED": _ANY_PAYLOAD,
        "TOPIC_STALE": _ANY_PAYLOAD,
    },
)
