"""Bars-only WS fan-out run and its verdict (E12-Q05 slice 4, #528; budget #6 gateway segment).

No new load script: `tests/load/ws/ws_load.js` already runs a bars-only workload through env
overrides (`FAMILIES=bars`, the W5 `bars-healthy` / `bars-saturated` phases), and
`tests/load/ws/profiles.json` belongs to E17-Q03 and is not edited here. `env` builds those
overrides; `judge` reads the summary's counters with the loss and lag checks that exist today.
What does not exist yet is listed by `pending()`, each with its owner. Loopback only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

CLIENT_LAG_P95_MS = 20.0  # profiles.json thresholds.client_lag_p95_ms
#: Counters that must be zero in a healthy run (the harness's own names, `lib/measure.js`).
MUST_BE_ZERO = ("cv_seq_gaps", "cv_unplanned_closes", "cv_errors")
#: Catalogue metrics (20-architecture) the harness correlates with. Present means the run may
#: assert on them; the others are pending their owner. `bar_rebuild_*` belongs to E12-S12.
CATALOGUE_METRICS: tuple[tuple[str, str], ...] = (
    ("cv_ws_overflow_total", "pending E17 gateway ladder"),
    ("cv_ws_conflated_total", "pending E17-T06"),
    ("cv_ws_queue_frames", "pending E17 gateway"),
    ("cv_ws_queue_bytes", "pending E17 gateway"),
    ("bar_build_latency_seconds", "pending E12-S04 emitter"),
    ("bar_builder_fanout_latency_seconds", "pending E12-S01 emitter"),
    ("bar_rebuild_duration_seconds", "E12-S12 (#535)"),
)
#: Budget #6 is "book update -> outbound frame", backend-internal: this run sees only the
#: gateway segment, client side.
BUDGET_6_LABEL = "gateway segment"


def env(*, lagging_rtt_ms: int = 0) -> dict[str, str]:
    """ws_load.js overrides for the bars-only run; `lagging_rtt_ms` > 0 is the `bars-saturated`
    leg (a lagging consumer by RTT delay: the client library has no true slow reader yet)."""
    if lagging_rtt_ms < 0:
        raise ValueError("lagging_rtt_ms must be >= 0")
    out = {"PROFILE": "W5", "FAMILIES": "bars"}
    if lagging_rtt_ms:
        out["RTT_DELAY_MS"] = str(lagging_rtt_ms)
    return out


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    measured: float
    limit: float
    passed: bool


def judge(counters: Mapping[str, float], client_lag_p95_ms: float) -> list[Check]:
    """No loss, no errors, and other clients' lag within the budget (AC4's loss and 'others
    unaffected' halves). A missing counter is an error, never a pass."""
    out = [Check(n, float(counters[n]), 0.0, counters[n] == 0) for n in MUST_BE_ZERO]
    out.append(
        Check(
            "client_lag_p95_ms",
            client_lag_p95_ms,
            CLIENT_LAG_P95_MS,
            client_lag_p95_ms < CLIENT_LAG_P95_MS,
        )
    )
    return out


def pending() -> list[str]:
    rows = [f"{name}: {owner}" for name, owner in CATALOGUE_METRICS]
    rows.append(
        "slow consumer at 1/10 rate, conflate then disconnect: pending "
        "(true slow reader in lib/client.js, E17-Q03)"
    )
    return rows
