"""The §15.10 `MachineStateUpdate` check (E17-T08; `23-ws-protocol.md` §6.4): the `machines`
registry runs it before it records a payload, so a feed defect is refused and logged, never served.
Written by hand, since the bundled schema (`docs/plan/ws-schema.json`) is not packaged; a test pins
it to that schema. It is stricter only in that `tags` are sorted (§6.4), an integer is never a
float, and a pattern never matches up to a trailing newline (ECMA-262 `$`)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from itertools import pairwise
from typing import Any, Final

from candleviewer.ws.topics import MACHINE_ENTITY_KIND

Check = Callable[[object], bool]


def _match(pattern: str) -> Check:
    regex = re.compile(pattern)
    return lambda value: isinstance(value, str) and regex.fullmatch(value) is not None


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _flag(value: object) -> bool:
    return isinstance(value, bool)


_IDENT: Final = _match("[a-z][a-z0-9_]{0,63}")
_HASH: Final = _match("[0-9a-f]{64}")
_ENV: Final = _match("live|demo|testnet")  # common `environment`
_SYMBOL: Final = _match("[A-Z0-9]{2,20}USDT")  # common `symbol`
_REQUIRED: Final = frozenset(
    {"machine_kind", "state", "tags", "degraded", "machine_hash", "environment", "updated_at_ms"}
)
_FIELDS: Final = _REQUIRED | {"regions", "context_summary"}
#: §6.4, §15.10: each `machine_kind` that may send a `context_summary`, its keys and their types.
_SUMMARY: Final[Mapping[str, Mapping[str, Check]]] = {
    "order": {"symbol": _SYMBOL, "halted_by_kill": _flag, "recon_misses": _count},
    "alert": {
        "severity": _match("debug|info|warning|error|critical"),
        "delivery_attempts": _count,
        "storm_count": _count,
    },
    "recording": {"symbol": _SYMBOL, "gap_count_24h": _count},
    "book": {"symbol": _SYMBOL, "resync_count": _count},
    "session": {"mfa_satisfied": _flag, "step_up_failures": _count},
    "kill_switch": {"scope": _match("global|accounts"), "cancel_working": _flag, "flatten": _flag},
}


def check_machine_payload(kind: str, payload: Mapping[str, Any]) -> str | None:
    """None when `payload` is a §15.10 `MachineStateUpdate` of an entity of `kind` (its
    `machine_kind` one of that kind's charts, §6.4), else the first field that breaks it
    (`fields` for a missing or unknown one): a name, never a value (C-12.6)."""
    if not payload.keys() >= _REQUIRED or not payload.keys() <= _FIELDS:
        return "fields"
    machine, tags = payload["machine_kind"], payload["tags"]
    if not isinstance(machine, str) or MACHINE_ENTITY_KIND.get(machine) != kind:
        return "machine_kind"
    if not _IDENT(payload["state"]):
        return "state"
    if "regions" in payload and not (
        isinstance(regions := payload["regions"], dict)
        and 2 <= len(regions) <= 4
        and all(_IDENT(k) and _IDENT(v) for k, v in regions.items())
    ):
        return "regions"
    if not (
        isinstance(tags, list)
        and len(tags) <= 32
        and all(map(_IDENT, tags))
        and all(a < b for a, b in pairwise(tags))  # unique, and sorted (§6.4)
    ):
        return "tags"
    for name, check in (("degraded", _flag), ("machine_hash", _HASH), ("environment", _ENV)):
        if not check(payload[name]):
            return name
    if not (_count(at := payload["updated_at_ms"]) and at <= 2**53 - 1):  # common `epochMs`
        return "updated_at_ms"
    allowed = _SUMMARY.get(machine, {})
    if "context_summary" in payload and not (
        isinstance(summary := payload["context_summary"], dict)
        and summary
        and all(key in allowed and allowed[key](value) for key, value in summary.items())
    ):
        return "context_summary"
    return None
