"""candleviewer.statechart.config — E50-T59.

Static configuration for `factory.py`: the per-lane inbox bound, service
pool size, the shared start-timeout, and the per-machine `CV_EVENT_SCHEMAS`
map each binding module fills at import time.

This module is deliberately data-only (29-statechart-adoption-plan.md §1.1)
so it can be imported anywhere — including `registry.py`, `tools/
lint_statecharts.py` and tests — without tripping CV-LINT-IMPORT (it never
imports `xstate_statemachine`).
"""

from __future__ import annotations

from typing import Any, Final, Literal

#: The three lanes every catalogue machine is assigned to
#: (29-statechart-adoption-plan.md §1.2, CV-C13). Order-path charts run on
#: a dedicated loop and never share one with the platform lane.
Lane = Literal["order", "control", "platform"]

LANES: Final[tuple[Lane, ...]] = ("order", "control", "platform")

#: `max_queue_size` per lane (`Interpreter(..., overflow_policy="refuse")`,
#: CV-C36). The order lane is deliberately the smallest bound: a full order
#: inbox must refuse fast (503 + page) rather than let latency-sensitive
#: commands queue behind a backlog. Control and platform lanes carry more
#: slack because their events are lower-frequency and idempotent-safe to
#: retry.
CV_INBOX_BOUND: Final[dict[Lane, int]] = {
    "order": 64,
    "control": 128,
    "platform": 256,
}

#: `service_pool_size` per lane (29-statechart-adoption-plan.md §1.2,
#: MUSTNOT-08: <=200 concurrent invoked children per process across every
#: lane combined — 32 + 8 + 16 = 56, well inside that ceiling per machine
#: instance).
CV_SERVICE_POOL: Final[dict[Lane, int]] = {
    "order": 32,
    "control": 8,
    "platform": 16,
}

#: `await asyncio.wait_for(interp.start(), CV_START_TIMEOUT)` (CV-C56). A
#: timeout here is a hard startup failure, never a retry — this is the only
#: detector the wrapper has for the CV-C51 unsatisfiable-cycle hang.
CV_START_TIMEOUT: Final[float] = 5.0

#: Bound on the B1 `killed` entry's exchange cancel (#1650). No cancel timeout
#: existed elsewhere in the repo; E29 may replace it with the OMS cancel budget.
#: On timeout the kill proceeds (audited); reconciliation re-syncs (C-2.5).
CV_KILL_CANCEL_TIMEOUT: Final[float] = 5.0

#: Bound on B1's write-ahead step (#847): `persist_event` awaits the OMS's `order_events` write
#: inside `asyncio.timeout(CV_PERSIST_TIMEOUT)`. A store that does not answer in time refuses the
#: step, and `actionErrorPolicy: "rollback"` leaves the machine as it was (24 Sec.8.2 S7, S11).
#: The p95 budget of a whole transition is 5 ms; this bounds a stalled store, not a slow one. The
#: order store's server-side statement cap is longer (`CV_OMS_STATEMENT_TIMEOUT_MS`, 2 s by default
#: and 1.5 s at least, #845), so a COMMIT in flight may land after the binding gave up: it raises
#: `StepOutcomeUnknown`, and the OMS facade rebuilds the order from its events, where the row
#: decides.
CV_PERSIST_TIMEOUT: Final[float] = 1.0

#: Bound on one command attempt of a B1 service (#847): `place` (with its lookups), `cancel`,
#: `amend` and `attach_stop` through the OMS's command port. A backstop above the adapter's own
#: call timeouts: a port that does not answer in time fails the attempt with `TimeoutError`, an
#: ambiguous outcome, so the order lands in `unknown` (24 Sec.8.2 S1) or the stop in `sl_missing`.
CV_COMMAND_TIMEOUT: Final[float] = 10.0

#: `maxIterations` default sized against the descent plateau
#: (`limit + 3`, CV-C62); individual chart JSON may declare its own value
#: when the descent plateau requires it, but every chart must set the key
#: explicitly (`registry`/`schema.py` requires the field to be present).
CV_DEFAULT_MAX_ITERATIONS: Final[int] = 500

#: Snapshot envelope version floor (E50-T02, 28-statechart-catalogue.md
#: "Envelope version floor is 3 (v3 carries chain_trips)"). Every call to
#: `Interpreter.from_snapshot(..., minimum_version=SNAPSHOT_V)` and every
#: `seal(..., version=SNAPSHOT_V)` in `persistence.py` (E50-T10/T49) must
#: use this constant rather than a literal `3`, so a future envelope-floor
#: bump is a one-line change with every call site following automatically.
#: The upstream library's own `SNAPSHOT_VERSION` (currently 3 in 0.9.1) is
#: a *ceiling* on what this constant may be set to — `restore()` refuses a
#: newer-than-library version outright — but this project pins its own
#: floor independently so a future library bump does not silently lower
#: our accepted minimum.
SNAPSHOT_V: Final[int] = 3

#: Machine key -> event name -> JSON-Schema, passed to `create_machine(event_schemas=...)` for
#: that machine only (CV-C-strict: an unknown event or a payload its schema refuses is refused
#: at `send()`). Keyed by machine since #847: charts share event names with different payloads
#: (B1's closed `EXEC`, `CANCEL`, `KILL`, `SL_DEADLINE` and `SL_OBSERVED`; B3's, B2's, B8's and
#: the rest stay permissive). A machine with no entry gets an empty map, and `strict=True` still
#: refuses every event its chart does not declare.
CV_EVENT_SCHEMAS: dict[str, dict[str, dict[str, Any]]] = {}


def register_event_schemas(machine_key: str, schemas: dict[str, dict[str, Any]]) -> None:
    """Merge *schemas* into *machine_key*'s map in `CV_EVENT_SCHEMAS`.

    Called once per binding module at import time (`bindings/b01_order.py`, etc.), so
    `factory.make_machine` passes each machine the schemas its binding registered. Raises on an
    event registered for the same machine with a different schema, since that would silently
    change which validation wins; another machine's schema for the same name is independent.
    """
    bucket = CV_EVENT_SCHEMAS.setdefault(machine_key, {})
    for name, schema in schemas.items():
        existing = bucket.get(name)
        if existing is not None and existing != schema:
            raise ValueError(
                f"event schema collision for '{machine_key}' event '{name}': already registered "
                "with a different schema"
            )
        bucket[name] = schema
