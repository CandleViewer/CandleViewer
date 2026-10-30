"""The cells of the E28-X03 RBAC matrix (#976), generated, never listed by hand.

Every operation of `tests/contract/rbac/matrix.yaml` (Security-owned, read and never edited here)
whose path is an E28 path (`E28_PATHS`), for every matrix actor, in every situation its route can
name (`_world.SITUATIONS`): an account, group or definition granted to `manager_with_grant`, one
granted to no one, and one with a member on each (so every write has its cross-account cells).
Each cell's expectation comes from the row's outcome and the scope rule (SR-051, SR-E28-21,
SR-E29-13):

- `401 unauthenticated` and `403 forbidden` are the row's, but an unsafe call with no session,
  which the CSRF guard refuses first (`403 csrf_token_invalid`, SR-041);
- an allowed caller acting on what its grants do not cover is refused as the route documents it:
  a read is the one unaudited `404 not_found` a missing object answers (PF-I06, anti-enumeration),
  the preview `403 account_scope_denied`, audited;
- the Owner, whose empty grants mean every account, is allowed everywhere the row allows.

The rows `not_mounted` today (`createTradeGroup`, amend and cancel: E34) have no cells; the meta
check fails the day one is served without them. The `trade_groups` WS topic's cells are the
`topics` row's, run by `test_ws_scope.py`.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from typing import Any, Final

import yaml

from tests.contract.rbac.rbac_harness import ACTORS, MATRIX_PATH, actor_grants
from tests.security.e28._world import SITUATIONS

E28_PATHS: Final = re.compile(
    r"^/(exchange-accounts/\{accountId\}/(profiles|default-profile)|trade-groups"
    r"|trade-group-definitions)(/|$)"
)
WS_TOPIC: Final = "trade_groups"
PREVIEW: Final = "POST /trade-groups/preview"
#: The ticket that owns the E28 rows of `account_scope` (`delegated`), so its cells are these.
DELEGATED: Final = "E28-X03 (#976)"
#: The lists name no one account: one situation, every caller.
LISTS: Final = frozenset({"GET /trade-groups", "GET /trade-group-definitions"})


@functools.cache
def matrix() -> dict[str, Any]:
    with MATRIX_PATH.open(encoding="utf-8") as fh:
        loaded: dict[str, Any] = yaml.safe_load(fh)
    return loaded


def rows(state: str | None = None) -> dict[str, dict[str, Any]]:
    """The E28 operations' rows (of `state`, when given), by `METHOD /path`."""
    return {
        key: row
        for key, row in matrix()["operations"].items()
        if E28_PATHS.match(key.split(" ", 1)[1]) and state in (None, row["state"])
    }


def situations(key: str) -> tuple[str, ...]:
    """Where a cell of `key` is run: what its path or body names."""
    if "{accountId}" in key:
        return ("granted", "foreign")
    return ("-",) if key in LISTS else ("granted", "foreign", "mixed")


@dataclass(frozen=True)
class Cell:
    key: str
    actor: str
    at: str
    expect: str  # "allow", or `<status> <problem code>`

    @property
    def id(self) -> str:
        return f"{self.key}|{self.actor}|{self.at}"

    @property
    def denied(self) -> bool:
        return self.expect != "allow"


def expect(key: str, actor: str, at: str) -> str:
    outcome = rows()[key]["outcomes"][actor]
    if actor == "unauthenticated" and not key.startswith("GET "):
        return "403 csrf_token_invalid"  # SR-041: an unsafe call with no session never reaches RBAC
    if outcome != "allow":
        return {"401": "401 unauthenticated", "403": "403 forbidden"}[str(outcome)]
    if actor == "owner" or set(SITUATIONS[at]) <= set(actor_grants(actor)):
        return "allow"
    return "403 account_scope_denied" if key == PREVIEW else "404 not_found"


def cells() -> list[Cell]:
    return [
        Cell(key, actor, at, expect(key, actor, at))
        for key in sorted(rows("executed"))
        for actor in ACTORS
        for at in situations(key)
    ]


def ws_outcomes() -> dict[str, str]:
    """The `trade_groups` topic row: each actor's `sub` outcome."""
    outcomes: dict[str, str] = matrix()["topics"][WS_TOPIC]["outcomes"]
    return outcomes
