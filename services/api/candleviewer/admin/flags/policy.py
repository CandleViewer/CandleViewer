"""Pure write policy of the feature-flag service (E42-T03, module M21): no I/O.

A write is judged on the flag's row as stored under its lock (`22-api-openapi.yaml`
`setFeatureFlag`): `step_up_class` is the one elevation it needs, and `stored_transition` says
whether it changed the stored value in the way the maintenance notice and audit follow. A row
that is missing or does not fit the flag's kind counts as unknown (`readable`). A kill-switch-class
flag's engaged value comes from its spec, never its class (`24-internal-schemas.md` §16.2): the
value that is not its default, `true` for `maintenance.mode` and `false` for `rules.enabled`.
"""

from __future__ import annotations

from typing import Literal

from candleviewer.admin.flags.registry import FlagSpec, FlagValue, value_matches
from candleviewer.admin.flags.resolver import StoredFlag

StepUpClass = Literal["killswitch", "live_enablement", "flags"]


def readable(spec: FlagSpec, row: StoredFlag | None) -> FlagValue | None:
    """The row's stored value, or `None` when the row is missing or unreadable (unknown)."""
    return row.value if row is not None and value_matches(spec, row.value) else None


def engaged_value(spec: FlagSpec) -> FlagValue:
    """The value a transition from unknown announces: a kill-switch-class flag's engaged value,
    the one that is not its default (24 §16.2), and `True` for any other flag."""
    return (not spec.default) if spec.is_killswitch else True


def step_up_class(spec: FlagSpec, row: StoredFlag, value: object) -> StepUpClass:
    """The one elevation writing `value` needs: releasing a kill switch (writing the value that
    is not its engaged one over a row that does not hold it; an unreadable row counts as engaged)
    needs `killswitch`, writing `true` to the live gate `live_enablement` whatever is stored, any
    other write `flags`."""
    if spec.is_killswitch:
        released = not engaged_value(spec)
        if value is released and readable(spec, row) is not released:
            return "killswitch"
    return "live_enablement" if spec.requires_evidence and value is True else "flags"


def stored_transition(spec: FlagSpec, before: StoredFlag | None, after: StoredFlag) -> bool:
    """A real transition of the stored value, the only one the maintenance notice and audit
    follow. An unknown (unreadable or missing) row to the flag's engaged value counts, as a boot
    that finds it stored does; unknown to any other value does not."""
    was = readable(spec, before)
    return after.value != was and (was is not None or after.value is engaged_value(spec))
