"""The profile table both sides read: `tests/load/ws/profiles.json` (k6 reads it with `open()`)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROFILES = Path(__file__).resolve().parents[4] / "tests" / "load" / "ws" / "profiles.json"
#: The gateway's own route (`ws/gateway.py` WS_PATH); the fixture may mount it under a prefix
#: (`/api/v1/ws`, 23 2.1). `tests/load/ws/lib/profile.js` `wsUrl` accepts the same paths.
GATEWAY_PATH = "/ws"
_WS_PATH = re.compile(r"(?:/[A-Za-z0-9_~-][A-Za-z0-9._~-]*)*/ws")


def load(path: Path = PROFILES) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def resolve(table: dict[str, Any], name: str) -> dict[str, Any]:
    """A profile with its `base` and the table's `defaults` applied; the profile wins."""
    raw = table["profiles"][name]
    base = resolve(table, raw["base"]) if "base" in raw else dict(table["defaults"])
    return {**base, **{k: v for k, v in raw.items() if k != "base"}}


def topics(table: dict[str, Any], prof: dict[str, Any]) -> list[tuple[str, str]]:
    """The `(family, channel)` list one connection of `prof` subscribes: its workspace's families
    (limited to `prof["families"]`) on each symbol, but `bars` on the first `bars_symbols` and
    `footprint` on the first `footprint_symbols` only: both lease a bar series, and the gateway
    admits 8 distinct series per user (23 6.1)."""
    cap = {"bars": prof.get("bars_symbols"), "footprint": prof.get("footprint_symbols")}
    out: list[tuple[str, str]] = []
    for i, sym in enumerate(table["symbols"][: prof["symbols"]]):
        for fam in table["workspaces"][prof["workspace"]]:
            limit = cap.get(fam)
            if limit is None:
                limit = prof["symbols"]
            if fam in prof["families"] and i < limit:
                out.append((fam, table["topics"][fam]["ch"].replace("{s}", sym)))
    return out


def ws_path(value: str) -> str:
    """`value` if the fixture can serve the gateway there: `/ws`, or plain segments and `/ws`."""
    if not _WS_PATH.fullmatch(value):
        raise ValueError(f"ws path {value!r}: expected /ws or a prefix and /ws, as /api/v1/ws")
    return value


def ws_prefix(value: str) -> str:
    """What goes in front of the gateway's `/ws` route to serve it at `value` (`''` for `/ws`)."""
    return ws_path(value).removesuffix(GATEWAY_PATH)
