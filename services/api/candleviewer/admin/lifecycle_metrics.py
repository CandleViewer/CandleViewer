"""User lifecycle metrics (E42-T04 S4, #965 Observability, R7), via the facade, served on the
scraped registry with `env` by `export_user_lifecycle_metrics`. The label values are closed sets,
declared here and pinned by tests to the module that writes each: the disable's results and the
cascade's steps and outcomes in `admin/user_disable.py`, and the grants push (`step`
`grants_push`, `outcome` `pushed`, `timeout` or `failed`) in `admin/account_access.py` (#2648).
Every series is bound at import, so the first failure after a restart is an increase that the
lifecycle tickets in `infra/prometheus/alerts/system_ticket.yml` can see."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from candleviewer.observability.metrics import CollectorRegistry, Counter, ReexportCollector

#: `action` -> its `result`s: a change, AC5's no-op, each refusal, or an unexpected error.
ACTION_RESULTS: Final[Mapping[str, tuple[str, ...]]] = {
    "disable": (
        *("disabled", "noop", "forbidden", "self_target", "not_found", "positions_unknown"),
        *("last_owner", "audit_unavailable", "error"),
    ),
}
#: `step` -> the `outcome`s it can count, no more (a value no call reaches is a series at 0 for
#: good). Each step after the commit (`user_disable.STEPS`) runs on every call and passes or fails
#: (cut off too); B16 and the invite revoke may have nothing to do. The closing record of a change
#: that did not commit is one attempt. The grants push: done, still running when the request
#: stopped waiting, or failed.
STEP_OUTCOMES: Final[Mapping[str, tuple[str, ...]]] = {
    "socket_close": ("ok", "failed"),  # S7: every call closes every socket of the user
    "session_sweep": ("ok", "failed"),
    "b16_revoke": ("ok", "failed", "skipped"),  # skipped: no session revoked or swept
    "scope_refresh": ("ok", "failed"),
    "rule_disarm": ("ok", "failed"),
    "invite_revoke": ("ok", "failed", "skipped"),  # skipped: the user was not invited
    "closing_record": ("ok", "failed"),
    "grants_push": ("pushed", "timeout", "failed"),
}

user_lifecycle_total = Counter(
    "cv_user_lifecycle_total",
    "User lifecycle calls by action and result (refusals and failures included).",
    ["action", "result"],
)
user_lifecycle_steps_total = Counter(
    "cv_user_lifecycle_steps_total",
    "User lifecycle steps by outcome (R7): disable cascade, closing record, grants push.",
    ["step", "outcome"],
)


def _bind_every_series() -> None:
    """Bind every value now: a series created at its first event gives `increase()` nothing to
    subtract, so the first failure after every restart would never alert."""
    for action, results in ACTION_RESULTS.items():
        for result in results:
            user_lifecycle_total.labels(action=action, result=result)
    for step, outcomes in STEP_OUTCOMES.items():
        for outcome in outcomes:
            user_lifecycle_steps_total.labels(step=step, outcome=outcome)


_bind_every_series()

EXPORTED_NAMES: Final = frozenset({"cv_user_lifecycle_total", "cv_user_lifecycle_steps_total"})


def export_user_lifecycle_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the lifecycle series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})
