"""candleviewer.statechart.bindings.b12_replay — MachineLogic for B12 `replay` (E26-T01).
Chart: `machines/B12.replay.machine.json` (names fixed by the contract; bodies only).

Statecharts record, synchronous code enforces (C-2.21): `replay.sessions_service` validates
every control event before it is sent, and the chart decides legality. The session facts the
service seeds through `factory.build(ctx=...)` arrive under `context["input"]` (the library never
merges creation input into declared keys), so `facts()` is the one read of them: the declared
keys once an action has pinned them, else the seeded input. Actions publish plain values through
a hook attached per interpreter (`attach_hook`; bindings never import `replay`/`audit`). Guards
are pure and total (A6); actions and services are `async def` (CV-C67).

Playback (`start_clock`, `stop_clock`, `slow_clock`) and the data services (`seek_and_prime`,
`emit_one_step`) stay idempotent no-ops: the replay clock and the seek/step data path are owned
by E26-T03/T04 and E36, which replace these bodies (never the names).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

import structlog

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: `hook(name, facts)`; names: cursor, speed, coverage, error, killed. Bound PER INTERPRETER by
#: its owner via `attach_hook` (never a module global: two services must not share a sink).
Hook = Callable[[str, Mapping[str, object]], Awaitable[None]]

_HOOK_ATTR = "cv_b12_hook"
#: The session facts the owner seeds at build (B12.1 context keys).
FACT_KEYS: Final = (
    "session_id", "symbols", "range_start", "range_end", "cursor", "speed", "loop",
    "paper_account_id", "coverage_gaps",
)  # fmt: skip
SPEED_MIN: Final = 0.1
SPEED_MAX: Final = 100.0
#: `error` is persisted as `error_message`: a leading identifier token (an exception class
#: name), never a path, a message or a traceback (SR-097).
_ERROR_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def attach_hook(interp: object, hook: Hook) -> None:
    """Bind *hook* to one interpreter (call right after `build`/`restore`)."""
    setattr(interp, _HOOK_ATTR, hook)


def facts(context: Mapping[str, Any]) -> dict[str, Any]:
    """Pure merged view of the session facts plus `error` (seeded input until pinned)."""
    out = {k: context.get(k) for k in FACT_KEYS}
    seeded = context.get("input")
    if context.get("session_id") is None and isinstance(seeded, Mapping):
        out.update({k: seeded[k] for k in FACT_KEYS if k in seeded})
    out["error"] = context.get("error")
    return out


def _pin(context: dict[str, Any]) -> None:
    """Copy the seeded facts into the declared keys once, before any action mutates one."""
    if context.get("session_id") is None:
        context.update({k: v for k, v in facts(context).items() if k in FACT_KEYS})


async def _call_hook(interp: object, name: str, context: dict[str, Any]) -> None:
    hook = getattr(interp, _HOOK_ATTR, None)
    if hook is None:
        logger().warning("b12_hook_missing", hook=name)
        return
    await hook(name, facts(context))


def _payload(event: Any) -> dict[str, Any]:
    for attr in ("payload", "data"):
        v = getattr(event, attr, None)
        if isinstance(v, dict):
            return v
    return event if isinstance(event, dict) else {}


def _guard_error(name: str, exc: Exception) -> bool:
    logger().error("b12_guard_error", guard=name, error=type(exc).__name__)
    return False


# --- guards: pure, total (B12.5, A6) -------------------------------------------------------


def loop_enabled(context: dict[str, Any], event: Any) -> bool:
    try:
        return facts(context).get("loop") is True
    except Exception as exc:
        return _guard_error("loop_enabled", exc)


# --- actions (CV-C67: coroutine functions registered directly) ------------------------------


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _pair(gap: object) -> list[int] | None:
    if not isinstance(gap, list | tuple) or len(gap) != 2:
        return None
    lo, hi = _int(gap[0]), _int(gap[1])
    return None if lo is None or hi is None else [lo, hi]


async def set_cursor(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """`seek`/`step` onDone: the service output names the primed cursor (E36); clamped to the
    range so `cursor_ts` always satisfies `rps_cursor`."""
    _pin(context)
    cursor = _int(_payload(event).get("cursor"))
    if cursor is not None:
        lo, hi = int(context["range_start"]), int(context["range_end"])
        context["cursor"] = min(max(cursor, lo), hi)
    await _call_hook(_i, "cursor", context)


async def reset_cursor_to_start(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    _pin(context)
    context["cursor"] = context["range_start"]
    await _call_hook(_i, "cursor", context)


async def set_speed(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """The service validated the multiplier (`rps_speed`); anything else leaves it unchanged."""
    _pin(context)
    speed = _payload(event).get("speed")
    if isinstance(speed, int | float) and not isinstance(speed, bool):
        if SPEED_MIN <= speed <= SPEED_MAX:
            context["speed"] = float(speed)
    await _call_hook(_i, "speed", context)


async def record_coverage(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """INV-B12-d: gaps the seek reports are recorded as `[lo, hi]` pairs, never interpolated;
    a malformed report keeps the previous gaps (none is ever dropped silently)."""
    _pin(context)
    gaps = _payload(event).get("coverage_gaps")
    if isinstance(gaps, list):
        pairs = [_pair(g) for g in gaps]
        if all(p is not None for p in pairs):
            context["coverage_gaps"] = pairs
        else:
            logger().error("b12_coverage_malformed", reported=len(gaps))
    await _call_hook(_i, "coverage", context)


async def record_error(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """onError arms hand an `ErrorEvent` (read `event.error`, CV-C21); `SOURCE_ERROR` names the
    failure on its payload. Only a sanitised token is kept (it becomes `error_message`)."""
    _pin(context)
    err = event.error if hasattr(event, "error") else None
    if err is None:
        err = _payload(event).get("error")
    name = type(err).__name__ if isinstance(err, BaseException) else str(err or "")
    token = _ERROR_TOKEN.match(name)
    context["error"] = token.group(0) if token else "source_error"
    await _call_hook(_i, "error", context)


async def audit_kill(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    _pin(context)
    context["error"] = "killed"
    await _call_hook(_i, "killed", context)


async def _clock_noop(*_args: object, **_kwargs: object) -> None:
    """`start_clock`/`stop_clock`/`slow_clock`: the replay clock is E26-T03/E36's (no-op here)."""
    return None


# --- services (idempotent under re-entry) ----------------------------------------------------


async def _data_noop(*_args: object, **_kwargs: object) -> None:
    """`seek_and_prime`/`emit_one_step`: the seek and step data path is E26-T04/E36's. Returning
    no output leaves `cursor`/`coverage_gaps` as seeded (`set_cursor`/`record_coverage`)."""
    return None


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "audit_kill": audit_kill,
    "record_coverage": record_coverage,
    "record_error": record_error,
    "reset_cursor_to_start": reset_cursor_to_start,
    "set_cursor": set_cursor,
    "set_speed": set_speed,
    "slow_clock": _clock_noop,
    "start_clock": _clock_noop,
    "stop_clock": _clock_noop,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "loop_enabled": loop_enabled,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "emit_one_step": _data_noop,
    "seek_and_prime": _data_noop,
}

register_binding_module("replay", __name__)

#: Permissive payload schemas, unchanged: `CV_EVENT_SCHEMAS` is one map keyed by event name
#: across every chart (a different `KILL`/`PAUSE`/`CANCEL` schema here would collide), so the
#: service validates each payload instead (`sessions_service._payload_for`).
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    {
        "CANCEL": _ANY_PAYLOAD,
        "CONSUMER_SLOW": _ANY_PAYLOAD,
        "DESTROY": _ANY_PAYLOAD,
        "KILL": _ANY_PAYLOAD,
        "PAUSE": _ANY_PAYLOAD,
        "PLAY": _ANY_PAYLOAD,
        "PREPARE": _ANY_PAYLOAD,
        "RANGE_END": _ANY_PAYLOAD,
        "SEEK": _ANY_PAYLOAD,
        "SET_SPEED": _ANY_PAYLOAD,
        "SOURCE_ERROR": _ANY_PAYLOAD,
        "STEP": _ANY_PAYLOAD,
    }
)
