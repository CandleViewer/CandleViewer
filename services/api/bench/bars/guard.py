"""Target allow-list and refuse-to-start guards (BQ-08 and BQ-09, ruled 15:33Z).

The E27-Q03 shape (`tests/load/k6/accounts/lib/guard.js`): loopback or the compose service `api`
only, an allow-list with no DNS lookup; an exchange host is refused first, naming why. No tailnet
entry. A trailing dot is another name and is refused, not normalised.
`assert_may_record` and `gate_mode` copy ws-load's refuse-to-start rules: a baseline is never
recorded under CI, and a gate lands with its same-runner baseline, else it only records.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# Case-insensitive, as accounts/lib/guard.js and its Python twin.
ALLOWED = re.compile(r"^http://(127\.0\.0\.1|localhost|\[::1\]|api)(:\d{1,5})?$", re.IGNORECASE)
EXCHANGE = re.compile(r"(^|\.)(bybit|bytick)\.com\.?(:\d+)?(/|$)", re.IGNORECASE)  # C-13.5


def assert_allowed_target(url: str) -> str:
    """Return `url` without a trailing slash if its origin is allow-listed, else raise."""
    base = url.rstrip("/")
    if EXCHANGE.search(re.sub(r"^https?://", "", base)):
        raise RuntimeError("refusing an exchange host as the load target (C-13.5)")
    if not ALLOWED.fullmatch(base):
        raise RuntimeError("refusing a target that is not loopback or the compose service `api`")
    return base


def assert_may_record(env: Mapping[str, str]) -> None:
    """ws-load refuses to record a baseline under CI: a run never rewrites its own gate."""
    if env.get("CI", "").lower() in ("1", "true"):
        raise RuntimeError("refusing to record a baseline under CI (06 §7.4: reviewed PR only)")


def gate_mode(baseline_profile: str | None, machine_profile: str) -> str:
    """`gate` only against a baseline recorded on this same runner profile, else `record-only`."""
    return "gate" if baseline_profile == machine_profile else "record-only"
