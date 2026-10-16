"""B16 `session` snapshot upcasters (E09-S04; #2301).

v0 -> v1 (E09-S04): the step-up rework added per-action-class elevation
context (`elevated_classes`, `step_up_failures`, `readonly_until_us`) and the
`readonly_downgrade` state. A snapshot taken at the pre-S04 hash lacks the
keys; the upcaster seeds them with the "never elevated, no failures, not
read-only" values, which is exactly what an old snapshot's state means.

v1 -> v2 (#2301): the idle lock became the non-terminal `auth.idle_locked`
state (`idle_locked`, `unlock_attempts`, `one_click_armed`). A v1 snapshot has
no lock state, so it is an unlocked session; the `sessions` row re-evaluates
`is_idle_locked` on first access (`SessionChart`).
"""

from __future__ import annotations

from typing import Any

from candleviewer.statechart.upcasters import register_upcaster

B16_FROM_HASH = "2d45266da1d7d17a68cbe76c93fc33043ef7f4fb2f2062c260ec3f3955989ffc"
B16_TO_HASH = "a6ac6e5bd897afff2533fcfcf027213aa5e6d022f8054d06232cf5a37dda178a"
B16_V1_HASH = B16_TO_HASH
B16_V2_HASH = "63e6c7c663f6aa40a783cbbe7f25a4f9db91db6247072d3c1c7913b46b4538d3"


def upcast_session_v0_to_v1(context: dict[str, Any]) -> dict[str, Any]:
    out = dict(context)
    out.setdefault("elevated_classes", {})
    out.setdefault("step_up_failures", 0)
    out.setdefault("readonly_until_us", None)
    return out


def upcast_session_v1_to_v2(context: dict[str, Any]) -> dict[str, Any]:
    out = dict(context)
    out.setdefault("idle_locked", False)
    out.setdefault("unlock_attempts", 0)
    out.setdefault("one_click_armed", None)
    return out


register_upcaster("session", B16_FROM_HASH, B16_TO_HASH, upcast_session_v0_to_v1)
register_upcaster("session", B16_V1_HASH, B16_V2_HASH, upcast_session_v1_to_v2)
