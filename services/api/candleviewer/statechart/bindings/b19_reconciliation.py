"""candleviewer.statechart.bindings.b19_reconciliation — MachineLogic for B19 `reconciliation`
(E29-T06 #914 PR 2a; 28-statechart-catalogue.md §B19, 24-internal-schemas.md §8.5). Chart:
`machines/B19.reconciliation.machine.json`, version 1, unchanged.

One interpreter per exchange account, built only through `cv.statechart.factory` and restored only
through `statechart.persistence` (BQ-1). B19 records the job's lifecycle; the pass is plain code
(`oms.reconciler`), which the services call phase by phase through the port the OMS sets
(`set_ports`), as the statechart package imports no `oms` module (C-3.1). No per-row work, no rate
admission and no timer runs here (28 §1.2, A2): `schedule_retry_deadline` asks the port's host timer
for `RETRY_DUE`, and B19's context holds no deadline. No action sends to its own interpreter
(CV-C25), and no entry action waits on it (CV-C51). Every action is total (A1): what a port raises
is logged by its class and paged where it matters, never raised.

The job's context: the account (`input.account_id`, copied to `account_id` by `stamp_start`, with
`input.auto_remediate`, the capability that keeps testnet reporting drift without acting on it,
INV-B19-d), the pass's `trigger` and `pass_id`, its fetch's start (`started_us`), the diff's and the
remediation's summaries, the failure count, the report's `unresolved` items, `outcome` and
`notices`, and whether a desync or stale episode is open (`episode_open`, 23 §15.9). All plain JSON,
so a snapshot stays compact (A8).

The stale rule (BQ-4, BQ-5; C-2.21): a failed fetch raises `FetchFailed`, which carries the plain
tracker's window (`failing_since_us`, `failed_at_us`, `window_us`), so `failures_exhausted` stays
pure over the event. The OMS sets the account's standing before it raises an exhausted one, so the
standing is set before B19 is told; `lock_account_for_new_orders` sets it again (idempotent), and
`unlock_account_for_new_orders`, the last action of the `OPERATOR_RESOLVED` arm, clears it only
after `audit_operator_resolved` recorded the decision. `KILL` is never sent to B19 (BQ-13): its
`audit_kill` logs and pages a defect, as the kill switch stops entries, never protection (C-2.6).

A static restore runs no entry action and resumes no invoke (LC-19): `redrive_after_restore` names
what the driver sends so a machine restored mid-pass never hangs (INV-B19-e), and the standing is
rebuilt from the restored state by the OMS (`oms/reconcile_standing.py`).

Unwired (no port set), the fetch fails with its stale window spent, so a job built before its
wiring locks in `stale_lockout` rather than report a clean pass that read nothing; the other
services return empty summaries and the actions do nothing. Each logs `reconcile_ports_unwired` at
ERROR, so such a job never acts and never hides.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Final, Protocol
from uuid import uuid4

import structlog

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: What started a pass (24 §8.5's trigger table), as the report records it.
TRIGGERS: Final = ("startup", "reconnect", "periodic", "manual", "unknown")
#: The trigger events and the trigger each records from `idle` (24 §8.5); from `divergent` every
#: trigger arrives as `SWEEP_DUE` with its `trigger` in the payload.
TRIGGER_EVENTS: Final[Mapping[str, str]] = {
    "startup": "STARTUP",
    "reconnect": "RECONNECTED",
    "unknown": "UNKNOWN_ORDER",
    "periodic": "SWEEP_DUE",
    "manual": "SWEEP_DUE",
}
#: The states a driver may persist B19 in (29 §1.3, quiescence): no service runs there.
REST_STATES: Final = frozenset({"idle", "backing_off", "divergent", "stale_lockout"})
#: A pass id as `str(UUID)` writes it, the only form the trigger events carry.
_UUID_TEXT: Final = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_MAX_TEXT: Final = 64
#: The kind of a fetch a job built before `set_ports` makes: failed, its window spent.
UNWIRED: Final = "unwired"


def window_elapsed(failing_since_us: int, failed_at_us: int, window_us: int) -> bool:
    """Whether a run of failed fetches has lasted the stale window (BQ-4): the one rule both the
    OMS's tracker and `failures_exhausted` apply, so the two never disagree."""
    return failed_at_us - failing_since_us >= window_us


class FetchFailed(Exception):
    """A failed fetch (24 §8.5's phase table): the only failure the stale rule counts. `kind` is
    the cause's class, never its text; the window is the OMS tracker's, so `failures_exhausted`
    reads it without a clock."""

    def __init__(self, kind: str, *, failing_since_us: int, failed_at_us: int, window_us: int):
        super().__init__(f"the reconciliation fetch failed ({kind})")
        self.kind = kind
        self.failing_since_us = failing_since_us
        self.failed_at_us = failed_at_us
        self.window_us = window_us

    @property
    def exhausted(self) -> bool:
        return window_elapsed(self.failing_since_us, self.failed_at_us, self.window_us)


class JobPorts(Protocol):
    """What the OMS wires for B19 (`oms.reconciler.ReconcilePhases`), keyed by the account's id as
    text. The phases return plain summaries; the effects are synchronous and never raise."""

    def now_us(self) -> int: ...

    async def fetch(self, account_id: str, *, pass_id: str, trigger: str) -> Mapping[str, Any]:
        """Step 1; raises `FetchFailed` for a failed fetch, the standing set first if exhausted."""
        ...

    async def diff(self, account_id: str, *, pass_id: str) -> Mapping[str, Any]: ...

    async def remediate(self, account_id: str, *, pass_id: str) -> Mapping[str, Any]: ...

    async def report(
        self,
        account_id: str,
        *,
        pass_id: str,
        trigger: str,
        episode_open: bool,
        failure: str | None,
    ) -> Mapping[str, Any]:
        """The report, its `oms.reconcile` record and its notices; never raises."""
        ...

    def observe(self, account_id: str, *, pass_id: str) -> None: ...

    def publish(self, account_id: str, notices: Sequence[Sequence[str]]) -> None: ...

    def fetch_failed(self, account_id: str, *, trigger: str) -> None: ...

    def schedule_retry(self, account_id: str, *, attempt: int) -> None: ...

    def lock(self, account_id: str, *, trigger: str) -> None: ...

    def stale(self, account_id: str) -> None: ...

    def unlock(self, account_id: str) -> None: ...

    def reset_failures(self, account_id: str) -> None: ...

    def alert(self, account_id: str, *, reason: str, page: bool) -> None: ...


_PORTS: list[JobPorts] = []


def set_ports(ports: JobPorts | None) -> None:
    """Wire (or clear, with `None`) the process-wide B19 port, once, at the composition root."""
    _PORTS.clear()
    if ports is not None:
        _PORTS.append(ports)


def ports_wired() -> bool:
    return bool(_PORTS)


def _ports(action: str) -> JobPorts | None:
    if not _PORTS:
        logger().error("reconcile_ports_unwired", action=action)
        return None
    return _PORTS[0]


# --- The context and the event ---------------------------------------------------------------


def _payload(event: Any) -> Mapping[str, Any]:
    """The library hands actions an `Event` (payload on `.payload`), not a dict."""
    payload = getattr(event, "payload", None)
    return payload if isinstance(payload, Mapping) else {}


def _kind(event: Any) -> str:
    kind = getattr(event, "type", "")
    return kind if isinstance(kind, str) else ""


def _done(event: Any) -> Mapping[str, Any]:
    """A service's summary, from its `done.invoke` event only (an error event has none)."""
    if not _kind(event).startswith("done.invoke."):
        return {}
    data = getattr(event, "data", None)
    return data if isinstance(data, Mapping) else {}


def _failure_of(event: Any) -> str | None:
    """The class of a service's failure (`ErrorEvent.error`), never its text (C-12.6)."""
    failure = getattr(event, "error", None)
    return None if failure is None else type(failure).__name__


def _fetch_failure(event: Any) -> str | None:
    """A failed fetch's own kind (`FetchFailed.kind`: the cause's class or a named check, never
    its text), where it names one that fits; else the failure's class (C-12.6)."""
    failure = getattr(event, "error", None)
    if isinstance(failure, FetchFailed) and (kind := _text(failure.kind)) is not None:
        return kind
    return _failure_of(event)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= _MAX_TEXT else None


def _account(context: Mapping[str, Any]) -> str | None:
    """The job's account: `account_id` once a pass copied it, else the build's `input`."""
    own = _text(context.get("account_id"))
    if own is not None:
        return own
    given = context.get("input")
    return _text(given.get("account_id")) if isinstance(given, Mapping) else None


def _pass_id(context: Mapping[str, Any]) -> str | None:
    value = context.get("pass_id")
    return value if isinstance(value, str) and _UUID_TEXT.fullmatch(value) else None


def _trigger(context: Mapping[str, Any]) -> str:
    value = context.get("trigger")
    return value if value in TRIGGERS else "periodic"


def _sweep_trigger(event: Any) -> str:
    """A `SWEEP_DUE`'s payload trigger: `manual` from the route, any trigger from `divergent`,
    `periodic` where it carries none (24 §8.5)."""
    value = _payload(event).get("trigger")
    return value if value in TRIGGERS else "periodic"


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _kinds(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(v) for v in value if isinstance(v, str)][:_MAX_TEXT]


def _effect(action: str, context: Mapping[str, Any], call: Callable[[JobPorts, str], None]) -> None:
    """One synchronous effect of an action, total (A1): unwired or a raising port is logged by
    its class, never raised."""
    ports, account = _ports(action), _account(context)
    if ports is None or account is None:
        return
    try:
        call(ports, account)
    except Exception as exc:
        logger().error("reconcile_effect_failed", action=action, failure=type(exc).__name__)


# --- Guards (pure, total, deny by default: A6) -----------------------------------------------


def divergences_found_and_auto_remediate(context: Mapping[str, Any], event: Any) -> bool:
    """The diff planned at least one action (each a divergence, a missing or looser stop
    included, BQ-18) and the account's capability lets the pass act (INV-B19-d)."""
    return _count(_done(event).get("divergences")) > 0 and context.get("auto_remediate") is True


def failures_exhausted(context: Mapping[str, Any], event: Any) -> bool:
    """The fetch has failed for the stale window (BQ-4), as the failure itself records it."""
    failure = getattr(event, "error", None)
    return isinstance(failure, FetchFailed) and failure.exhausted


def unresolved_divergences(context: Mapping[str, Any], event: Any) -> bool:
    """The report left an item for the Owner (24 §8.5's phase table)."""
    return _count(context.get("unresolved")) > 0


# --- Actions (each `async def`, total: A1, CV-C67) ----------------------------------------------


async def set_trigger_periodic(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    context["trigger"] = _sweep_trigger(event)


async def set_trigger_reconnect(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    context["trigger"] = "reconnect"


async def set_trigger_startup(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    context["trigger"] = "startup"


async def set_trigger_unknown(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    context["trigger"] = "unknown"


async def stamp_start(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """`fetching`'s entry, every pass: the account and its capability from the build's input, the
    trigger a `SWEEP_DUE` from `divergent` carries (any other arm set it already), and the pass's
    id: the trigger's own, the pass's again on `RETRY_DUE`, else a new one."""
    given = context.get("input")
    if isinstance(given, Mapping):
        account = _text(given.get("account_id"))
        if account is not None:
            context["account_id"] = account
        if isinstance(given.get("auto_remediate"), bool):
            context["auto_remediate"] = given["auto_remediate"]
    kind = _kind(event)
    if kind == "SWEEP_DUE":
        context["trigger"] = _sweep_trigger(event)
    context["trigger"] = _trigger(context)
    asked = _payload(event).get("pass_id")
    if kind != "RETRY_DUE" or _pass_id(context) is None:
        given_id = isinstance(asked, str) and _UUID_TEXT.fullmatch(asked) is not None
        context["pass_id"] = asked if given_id else str(uuid4())
    ports = _ports("stamp_start")
    context["started_us"] = ports.now_us() if ports is not None else 0
    context["divergences"], context["remediations"] = [], []
    context["unresolved"], context["last_failure"] = 0, None


async def emit_recon_started(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    logger().info(
        "reconcile_pass_started",
        account_id=_account(context),
        pass_id=_pass_id(context),
        trigger=_trigger(context),
    )


async def store_exchange_state(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    context["orders_checked"] = _count(_done(event).get("orders"))


async def bump_failures(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """A fetch that failed inside the stale window (24 §8.5's phase table), recorded by its own
    kind (`_fetch_failure`)."""
    context["consecutive_failures"] = _count(context.get("consecutive_failures")) + 1
    context["last_failure"] = _fetch_failure(event)
    trigger = _trigger(context)
    _effect("bump_failures", context, lambda p, a: p.fetch_failed(a, trigger=trigger))


async def schedule_retry_deadline(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """`backing_off`'s entry: the driver's host timer sends `RETRY_DUE`; no deadline is kept in
    context (A2), so after a restore the driver sends it again (INV-B19-e)."""
    attempt = _count(context.get("consecutive_failures"))
    _effect("schedule_retry_deadline", context, lambda p, a: p.schedule_retry(a, attempt=attempt))


async def store_divergences(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    context["divergences"] = _kinds(_done(event).get("kinds"))


async def record_diff_error(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """A diff that could not plan at all reports with its error (24 §8.5); the next trigger runs."""
    failure = event.error if hasattr(event, "error") else None
    context["last_failure"] = "unknown" if failure is None else type(failure).__name__
    logger().error(
        "reconcile_diff_failed",
        account_id=_account(context),
        pass_id=_pass_id(context),
        failure=context["last_failure"],
    )


async def store_remediations(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """The remediation's summary, or, on its `onError` arm, the failure's class."""
    context["remediations"] = _kinds(_done(event).get("kinds"))
    failure = _failure_of(event)
    if failure is not None:
        context["last_failure"] = failure


async def raise_critical_alert(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """A remediation that failed as a whole still reports, and pages (24 §8.5)."""
    _effect(
        "raise_critical_alert",
        context,
        lambda p, a: p.alert(a, reason="remediation_failed", page=True),
    )


async def persist_report(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """`reporting`'s first entry action, every pass (INV-B19-f): the report, written as its
    `oms.reconcile` record (24 §15.5), with what the next actions and the guard read: the items
    left for the Owner, the result, the notices and whether an episode stays open. A report that
    cannot be written still ends its pass, logged and paged by the port; none is left here."""
    context["unresolved"], context["outcome"], context["notices"] = 0, None, []
    ports, account, pass_id = _ports("persist_report"), _account(context), _pass_id(context)
    if ports is None or account is None or pass_id is None:
        return
    episode = context.get("episode_open") is True
    try:
        summary = await ports.report(
            account,
            pass_id=pass_id,
            trigger=_trigger(context),
            episode_open=episode,
            failure=_text(context.get("last_failure")),
        )
    except Exception as exc:
        logger().error("reconcile_report_failed", account_id=account, failure=type(exc).__name__)
        return
    context["unresolved"] = _count(summary.get("unresolved"))
    outcome = summary.get("outcome")
    context["outcome"] = outcome if isinstance(outcome, str) else None
    notices = summary.get("notices")
    context["notices"] = [
        [str(n[0]), str(n[1])]
        for n in (notices if isinstance(notices, list) else [])
        if len(n) == 2
    ]
    context["episode_open"] = summary.get("episode_open") is True


async def emit_recon_metrics(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    pass_id = _pass_id(context)
    if pass_id is not None:
        _effect("emit_recon_metrics", context, lambda p, a: p.observe(a, pass_id=pass_id))


async def reset_failures(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """Ends a failure run: a reported pass (a diff or remediation error is never counted), or
    the operator's decision on a stale account (BQ-4)."""
    context["consecutive_failures"] = 0
    _effect("reset_failures", context, lambda p, a: p.reset_failures(a))


async def broadcast_recon_complete(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """The report's account notices (23 §15.9), handed to the port; publishing is the wiring's."""
    notices = list(context.get("notices") or [])
    if notices:
        _effect("broadcast_recon_complete", context, lambda p, a: p.publish(a, notices))


async def raise_divergence_alert(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """`divergent`'s entry: items wait for the Owner, each paged by its own rule already."""
    _effect(
        "raise_divergence_alert", context, lambda p, a: p.alert(a, reason="divergent", page=False)
    )


async def lock_account_for_new_orders(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """`stale_lockout`'s entry records the lock; the standing was set before B19 was told
    (C-2.21), and this sets it again, idempotent, for any other way in."""
    trigger = _trigger(context)
    _effect("lock_account_for_new_orders", context, lambda p, a: p.lock(a, trigger=trigger))


async def page_owner(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """The stale episode: the Owner paged and `oms.account_stale` handed on, once per episode."""
    context["episode_open"] = True
    _effect("page_owner", context, lambda p, a: p.stale(a))


async def audit_operator_resolved(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """B19's record of the operator's unlock (INV-B19-b). `resolveReconciliation` writes the
    decision's `oms.reconcile` record (`stage: resolved`) before B19 is told (24 §15.5)."""
    logger().warning(
        "reconcile_operator_resolved",
        account_id=_account(context),
        decided_by=_text(_payload(event).get("decided_by")),
    )


async def unlock_account_for_new_orders(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """The arm's last action: the standing clears only once B19 recorded the decision (BQ-5)."""
    _effect("unlock_account_for_new_orders", context, lambda p, a: p.unlock(a))


async def audit_reconnect_while_locked(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """A reconnect never clears the lock nor pages again (INV-B19-b)."""
    logger().info("reconcile_reconnect_while_locked", account_id=_account(context))


async def audit_kill(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """`KILL` is never sent to B19 (BQ-13): one that arrives is a defect, logged and paged."""
    logger().critical("reconcile_kill_received", account_id=_account(context), cv_page=True)
    _effect("audit_kill", context, lambda p, a: p.alert(a, reason="kill_received", page=True))


# --- Services (each `async def`, idempotent under re-entry) -----------------------------------


async def fetch_exchange_state(_i: Any, context: dict[str, Any], _e: Any) -> Mapping[str, Any]:
    """Step 1 (24 §8.5): raises `FetchFailed` for a failed fetch. A job that cannot fetch at all
    (unwired, or with no account or pass id) fails with its stale window spent, so it locks
    rather than report a clean pass that read nothing (INV-B19-a)."""
    ports, account, pass_id = _ports("fetch_exchange_state"), _account(context), _pass_id(context)
    if ports is None or account is None or pass_id is None:
        kind = UNWIRED if ports is None else "unusable"
        if ports is not None:
            logger().error("reconcile_job_unusable", account_id=account, pass_id=pass_id)
        raise FetchFailed(kind, failing_since_us=0, failed_at_us=0, window_us=0)
    return await ports.fetch(account, pass_id=pass_id, trigger=_trigger(context))


async def diff_against_local(_i: Any, context: dict[str, Any], _e: Any) -> Mapping[str, Any]:
    """Steps 2 to 3d, and steps 4 and 5's tests, as a plan (BQ-18)."""
    ports, account, pass_id = _ports("diff_against_local"), _account(context), _pass_id(context)
    if ports is None or account is None or pass_id is None:
        return {}
    return await ports.diff(account, pass_id=pass_id)


async def apply_remediations(_i: Any, context: dict[str, Any], _e: Any) -> Mapping[str, Any]:
    """The plan, in 24 §8.5's order; step 5 always runs (C-2.6)."""
    ports, account, pass_id = _ports("apply_remediations"), _account(context), _pass_id(context)
    if ports is None or account is None or pass_id is None:
        return {}
    return await ports.remediate(account, pass_id=pass_id)


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "audit_kill": audit_kill,
    # OC-05 (#2204): stale_lockout leaves only on OPERATOR_RESOLVED (INV-B19-b).
    "audit_operator_resolved": audit_operator_resolved,
    "audit_reconnect_while_locked": audit_reconnect_while_locked,
    "broadcast_recon_complete": broadcast_recon_complete,
    "bump_failures": bump_failures,
    "emit_recon_metrics": emit_recon_metrics,
    "emit_recon_started": emit_recon_started,
    "lock_account_for_new_orders": lock_account_for_new_orders,
    "page_owner": page_owner,
    "persist_report": persist_report,
    "raise_critical_alert": raise_critical_alert,
    "raise_divergence_alert": raise_divergence_alert,
    "record_diff_error": record_diff_error,
    "reset_failures": reset_failures,
    "schedule_retry_deadline": schedule_retry_deadline,
    "set_trigger_periodic": set_trigger_periodic,
    "set_trigger_reconnect": set_trigger_reconnect,
    "set_trigger_startup": set_trigger_startup,
    "set_trigger_unknown": set_trigger_unknown,
    "stamp_start": stamp_start,
    "store_divergences": store_divergences,
    "store_exchange_state": store_exchange_state,
    "store_remediations": store_remediations,
    "unlock_account_for_new_orders": unlock_account_for_new_orders,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "divergences_found_and_auto_remediate": divergences_found_and_auto_remediate,
    "failures_exhausted": failures_exhausted,
    "unresolved_divergences": unresolved_divergences,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "apply_remediations": apply_remediations,
    "diff_against_local": diff_against_local,
    "fetch_exchange_state": fetch_exchange_state,
}

register_binding_module("reconciliation", __name__)


def redrive_after_restore(
    state: str, context: Mapping[str, Any]
) -> tuple[tuple[str, dict[str, Any]], ...] | None:
    """What the driver sends a machine restored in `state` (INV-B19-e, LC-19): a static restore
    resumes no invoke, so `fetching` is cancelled and its trigger sent again (its pass's id kept),
    `backing_off` takes its lost `RETRY_DUE`, and a rest state needs nothing. None for `diffing`
    and `remediating`, which no event leaves and which are never persisted (`REST_STATES`): the
    driver builds the job afresh and sends `STARTUP`."""
    if state == "backing_off":
        return (("RETRY_DUE", {}),)
    if state in REST_STATES:
        return ()
    if state != "fetching":
        return None
    trigger = _trigger(context)
    event = TRIGGER_EVENTS[trigger]
    payload: dict[str, Any] = {"trigger": trigger} if event == "SWEEP_DUE" else {}
    pass_id = _pass_id(context)
    if pass_id is not None:
        payload["pass_id"] = pass_id
    return (("CANCEL", {}), (event, payload))


def _closed(**properties: dict[str, Any]) -> dict[str, Any]:
    """A closed payload: these keys only, none required (an empty payload stays valid)."""
    return {"type": "object", "additionalProperties": False, "properties": properties}


_PASS_ID: Final = {"type": "string", "pattern": _UUID_TEXT.pattern}
_SHORT: Final = {"type": "string", "minLength": 1, "maxLength": _MAX_TEXT}
#: Every event B19 declares, each with a closed payload (28 B19.3; owning epics tighten them).
SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "CANCEL": _closed(),
    "KILL": _closed(reason=_SHORT),
    "OPERATOR_RESOLVED": _closed(decided_by=_SHORT, reason=_SHORT),
    "RECONNECTED": _closed(pass_id=_PASS_ID),
    "RETRY_DUE": _closed(),
    "STARTUP": _closed(pass_id=_PASS_ID),
    "SWEEP_DUE": _closed(trigger={"enum": list(TRIGGERS)}, pass_id=_PASS_ID),
    "UNKNOWN_ORDER": _closed(pass_id=_PASS_ID),
}
register_event_schemas("reconciliation", SCHEMAS)
