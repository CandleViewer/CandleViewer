"""candleviewer.statechart.factory — the ONLY construction site (E50-T59).

`build()` and (a thin delegate to `persistence.restore`, landing in
E50-T10/T49) `restore()` are the sole functions in the whole codebase that
may call `create_machine`, `Interpreter` or `SyncInterpreter`
(29-statechart-adoption-plan.md §1.2, CV-LINT-IMPORT). They apply the FINAL
mandatory config block from `28-statechart-catalogue.md` §1.3c
unconditionally — no caller kwarg can opt out of any part of it.

Restore (snapshot/HMAC/drain-journal, E50-T49) lives in
`persistence.Restorer`, which reuses `make_machine` / `apply_lane_config` /
`_cv_bring_up` from here. Plugin bodies (CvErrorHooks/CvMetricsPlugin/
CvAuditPlugin) are E50-T60.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import jsonschema
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    MachineNode,
    OverflowPolicy,
    PluginBase,
    QueueOverflowError,
    create_machine,
)
from xstate_statemachine.clock import Clock, RealClock
from xstate_statemachine.events import re_mint as re_mint

from candleviewer.statechart.bindings import load_binding_maps
from candleviewer.statechart.config import (
    CV_EVENT_SCHEMAS,
    CV_INBOX_BOUND,
    CV_SERVICE_POOL,
    CV_START_TIMEOUT,
    Lane,
)
from candleviewer.statechart.registry import Registry, default_registry

if TYPE_CHECKING:
    from candleviewer.statechart.persistence import (
        MachineKey,
        Restorer,
        RestoreResult,
        SealedSnapshot,
    )

#: Re-exported for `gateway.py` (E50-T15), which may not import the runtime
#: itself (CV-LINT-IMPORT) but must map an inbox refusal to 503 + page.
InboxFullError = QueueOverflowError

#: `re_mint` is re-exported for `gateway.cv_re_mint` only (CV-C68, CV-LINT-REMINT):
#: nothing else may call it.


class SyncInterpreterRefusedError(AssertionError):
    """Raised when anything requests the sync engine from this factory
    (MUSTNOT-06). Async `Interpreter` only."""


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Return value of `build()`: the started interpreter plus the
    `machine_hash` it was built from, so callers can bind the two together
    for supervision/audit without re-hashing the chart themselves."""

    interpreter: Interpreter[Any]
    machine_hash: str


def default_clock() -> Clock:
    """Wall clock for callers outside `statechart/` that must not import the
    runtime library to satisfy `build(clock=...)`."""
    return RealClock()


def _cv_bring_up(interp: Interpreter[Any]) -> None:
    """CV-C66': per-process bring-up work, called by `build()` and `restore()` before `start()`.
    `on_interpreter_start` fires on all paths, restores too (library #240), so it stays telemetry
    only: it may branch on `restored_from_snapshot`. Currently a no-op; what a restored machine
    needs once it has started is `cv_bring_up_restored`."""
    return None


def cv_bring_up_restored(interp: Interpreter[Any]) -> None:
    """CV-C66': a restored `start()` enters no state, so no plugin hears an `on_transition` for the
    state the machine comes back in. Each plugin with a `cv_bring_up(interpreter)`, which must not
    raise, is told here once (the feed publishes, 23 §6.4): after `start()`, before the replay."""
    for plugin in interp.plugins:
        bring_up = getattr(plugin, "cv_bring_up", None)
        if bring_up is not None:
            bring_up(interp)


def _assert_async_engine_only(*, sync: bool) -> None:
    if sync:
        raise SyncInterpreterRefusedError(
            "cv.statechart.factory builds the async Interpreter only "
            "(MUSTNOT-06); SyncInterpreter is not available through build()"
        )


def _event_validators(schemas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Adapt JSON-Schema dicts to the validator objects the library calls
    (`schema.validate(payload)`); a bare dict is not callable (QA #1634)."""
    return {name: jsonschema.Draft202012Validator(schema) for name, schema in schemas.items()}


def make_machine(machine_key: str, chart: dict[str, Any]) -> MachineNode[Any]:
    """`create_machine` with the mandatory config block (§1.3c). Shared by
    `build()` and `persistence.Restorer` so a restored machine is constructed
    exactly like a fresh one (E50-T49). The event schemas are *machine_key*'s
    own (`CV_EVENT_SCHEMAS` is keyed by machine, #847)."""
    maps = load_binding_maps(machine_key)
    logic: MachineLogic[Any] = MachineLogic(
        actions=maps.actions,
        guards=maps.guards,
        services=maps.services,
        strict=True,
    )
    return create_machine(
        chart,
        context_type=dict,
        logic=logic,
        strict_targets=True,
        event_schemas=_event_validators(CV_EVENT_SCHEMAS.get(machine_key, {})),
        strict_config=True,
    )


def apply_lane_config(interp: Interpreter[Any], lane: Lane) -> None:
    """Re-apply the per-lane interpreter settings to a restored interpreter.

    `Interpreter.from_snapshot` constructs `cls(machine, clock=clock)` only,
    so the inbox bound, `refuse` overflow policy, `strict` and service pool
    must be set before `start()` (E50-T49; same values as `build()`).
    """
    interp._max_queue_size = CV_INBOX_BOUND[lane]
    interp._overflow_policy = OverflowPolicy.RAISE
    interp.strict = True
    interp._service_pool_size = CV_SERVICE_POOL[lane]


async def build(
    machine_key: str,
    *,
    ctx: Any = None,
    clock: Clock,
    lane: Lane,
    plugins: tuple[PluginBase[Any], ...] = (),
    registry: Registry | None = None,
    sync: bool = False,
) -> BuildResult:
    """Construct, configure and start an `Interpreter` for *machine_key*.

    Applies the FINAL mandatory config block (28-statechart-catalogue.md
    §1.3c) unconditionally: `strict_config=True` + the chart's own
    `strictConfig`/`strict`/`strictTargets`/`onUnhandled`/`maxIterations`
    keys (already asserted present by `registry.validate()`), `strict=True`
    + the machine's own `CV_EVENT_SCHEMAS[machine_key]`, the per-lane
    inbox bound with `overflow_policy="refuse"`, the per-lane service pool
    size, the injected `clock=`, every plugin passed via `.use(...)`, bring-
    up, and a bounded `start()`.

    No extra kwargs reach the interpreter: `sync=True` raises
    `SyncInterpreterRefusedError` rather than constructing anything (there
    is no code path in this function that builds a `SyncInterpreter` at
    all — the parameter exists solely so a caller cannot get one by asking).
    """
    _assert_async_engine_only(sync=sync)

    reg = registry or default_registry()
    chart = reg.get(machine_key)
    chart_hash = reg.hash(machine_key)

    machine = make_machine(machine_key, chart)

    interp: Interpreter[Any] = Interpreter(
        machine,
        input=ctx,
        clock=clock,
        max_queue_size=CV_INBOX_BOUND[lane],
        # "refuse" (28-statechart-catalogue.md §1.3c) == OverflowPolicy.RAISE:
        # nothing is ever dropped silently, on any lane (CV-C36). The order
        # lane's gateway turns the resulting QueueOverflowError into a 503
        # plus a page (29-statechart-adoption-plan.md §1.2); that mapping
        # lives in gateway.py (E50-T15), not here.
        overflow_policy=OverflowPolicy.RAISE,
        strict=True,
        service_pool_size=CV_SERVICE_POOL[lane],
    )
    for plugin in plugins:
        interp.use(plugin)

    _cv_bring_up(interp)
    try:
        await asyncio.wait_for(interp.start(), CV_START_TIMEOUT)
    except TimeoutError as exc:
        raise TimeoutError(
            f"'{machine_key}' start() did not settle within "
            f"{CV_START_TIMEOUT}s (CV-C56) — hard startup failure, never a "
            "retry"
        ) from exc

    return BuildResult(interpreter=interp, machine_hash=chart_hash)


async def restore(
    restorer: Restorer,
    key: MachineKey,
    envelope: SealedSnapshot,
    *,
    extra_plugins: Sequence[Any] = (),
) -> RestoreResult:
    """Restore a machine from a sealed snapshot (29 §1.3, E50-T49).

    Thin delegation point: `from_snapshot` may only be called from
    `statechart/persistence.py` (CV-LINT-RESTORE), so the work lives in
    `persistence.Restorer.restore`. `extra_plugins` follow the restorer's own (E17-T08).
    """
    return await restorer.restore(key, envelope, extra_plugins=extra_plugins)
