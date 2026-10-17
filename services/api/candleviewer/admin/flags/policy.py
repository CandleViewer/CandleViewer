"""Pure write policy of the feature-flag service (E42-T03, module M21): no I/O.

A write is judged on the flag's row as stored under its lock (`22-api-openapi.yaml`
`setFeatureFlag`): `step_up_class` is the one elevation it needs, and `stored_transition` says
whether it changed the stored value in the way the maintenance notice and audit follow. A row
that is missing or does not fit the flag's kind counts as unknown (`readable`).
"""

from __future__ import annotations

from typing import Literal

from candleviewer.admin.flags.registry import FlagSpec, FlagValue, value_matches
from candleviewer.admin.flags.resolver import StoredFlag

StepUpClass = Literal["killswitch", "live_enablement", "flags"]


def readable(spec: FlagSpec, row: StoredFlag | None) -> FlagValue | None:
    """The row's stored value, or `None` when the row is missing or unreadable (unknown)."""
    return row.value if row is not None and value_matches(spec, row.value) else None


def step_up_class(spec: FlagSpec, row: StoredFlag, value: object) -> StepUpClass:
    """The one elevation writing `value` needs: releasing a kill switch needs `killswitch` (an
    unreadable row counts as engaged), writing `true` to the live gate `live_enablement` whatever
    is stored, any other write `flags`."""
    if spec.is_killswitch and value is False and readable(spec, row) is not False:
        return "killswitch"
    return "live_enablement" if spec.requires_evidence and value is True else "flags"


def stored_transition(spec: FlagSpec, before: StoredFlag | None, after: StoredFlag) -> bool:
    """A real transition of the stored value, the only one the maintenance notice and audit
    follow. An unknown (unreadable or missing) row to `True` counts, as a boot that finds a
    stored `True` does; unknown to `False` does not."""
    was = readable(spec, before)
    return after.value != was and (was is not None or after.value is True)
