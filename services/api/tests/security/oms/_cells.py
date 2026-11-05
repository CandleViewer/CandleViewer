"""The cells of the E29-X02 RBAC matrix (#982), generated, never listed by hand.

Every operation of `tests/contract/rbac/matrix.yaml` (Security-owned, read and never edited here)
whose path is an E29 path (`E29_PATHS`, as E28-X03's suite selects its own), for every matrix
actor, in every situation its route can name (`_world.SITUATIONS`). Each cell's expectation is a
refusal class, from the row's outcome and the scope rule (SR-E29-13, 24 Sec.8.4):

- `401` and `csrf` are the row's: a read with no session is `401 unauthenticated`, an unsafe call
  with none is refused by the CSRF guard first (`403 csrf_token_invalid`, SR-041);
- `role`, a caller lacking one of the row's permissions (its `403`): `403 forbidden`, before
  anything is read; the row's `403` for a caller holding them all is placeOrder's step 2 refusing
  the account the body names (`scope`);
- a caller the row allows, acting on what its grants do not cover: an id on an account it does
  not hold is the one `404 not_found` (`foreign`, audited) that an id nothing holds answers
  (`missing`, unaudited: the accepted Q12 residual); an account a body or a filter names is
  `403 account_scope_denied` (`scope`), the whole request refused;
- the Owner, whose empty grants mean every account, is allowed everywhere the row allows, but an
  id nothing holds is `missing` and an account nothing holds named in a body or a filter is
  `scope`.

The Gherkin's "403 for every disallowed combination" is the contract's code per class here (BQ-3).
The row `not_mounted` today (`PUT /positions/{positionId}/tpsl`) has no cells; the meta test fails
the day it is served without them. The WS topics are the `topics` rows of `WS_TOPICS`.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from typing import Any, Final

import yaml

from tests.contract.rbac.rbac_harness import (
    ACTORS,
    MATRIX_PATH,
    actor_grants,
    actor_permissions,
    load_contract,
)
from tests.security.oms._world import SITUATIONS

E29_PATHS: Final = re.compile(r"^/(orders|positions|executions)(/|$)")
#: 23's private topics of the OMS's data (the ticket's four) and B1's state topic.
WS_TOPICS: Final = ("orders", "executions", "positions", "wallet", "machines.order")
LISTS: Final = frozenset(
    {"GET /orders", "GET /positions", "GET /executions", "GET /executions/closed-pnl"}
)
#: The writes whose body names accounts: one (`exchange_account_id`) or a list.
NAMED: Final = {
    "POST /orders": "exchange_account_id", "POST /orders/cancel-all": "exchange_account_ids",
    "POST /positions/close-all": "exchange_account_ids",
}  # fmt: skip
#: Each refusal class's answer and the records it writes under the request's id: none for a
#: caller with no principal or the anti-enumeration `missing` 404 (a record would be the oracle).
ANSWER: Final = {
    "401": "401 unauthenticated", "csrf": "403 csrf_token_invalid", "role": "403 forbidden",
    "scope": "403 account_scope_denied", "foreign": "404 not_found", "missing": "404 not_found",
}  # fmt: skip
AUDITED: Final = {
    "401": [], "csrf": ["auth.csrf_refused"], "role": ["rbac.denied"], "scope": ["rbac.denied"],
    "foreign": ["rbac.denied"], "missing": [],
}  # fmt: skip


@functools.cache
def matrix() -> dict[str, Any]:
    with MATRIX_PATH.open(encoding="utf-8") as fh:
        loaded: dict[str, Any] = yaml.safe_load(fh)
    return loaded


@functools.cache
def contract() -> dict[str, Any]:
    """22, read once: it is large, and every actor's permissions and the meta test read it."""
    return load_contract()


def _permissions(actor: str) -> frozenset[str]:
    """The actor's permissions as the contract's `x-permissions` give them (the pack's seed)."""
    return actor_permissions(actor, contract())


def rows(state: str | None = None) -> dict[str, dict[str, Any]]:
    """The E29 operations' rows (of `state`, when given), by `METHOD /path`."""
    return {
        key: row
        for key, row in matrix()["operations"].items()
        if E29_PATHS.match(key.split(" ", 1)[1]) and state in (None, row["state"])
    }


def situations(key: str) -> tuple[str, ...]:
    """Where a cell of `key` is run: what its path, body or filter names."""
    if key in LISTS:
        return ("-", "granted", "foreign", "absent", "mixed")
    many = NAMED.get(key) == "exchange_account_ids"
    return ("granted", "foreign", "absent", *(("mixed",) if many else ()))


@dataclass(frozen=True)
class Cell:
    key: str
    actor: str
    at: str
    expect: str  # "allow", or a refusal class of `ANSWER`

    @property
    def id(self) -> str:
        return f"{self.key}|{self.actor}|{self.at}"

    @property
    def denied(self) -> bool:
        return self.expect != "allow"


def held(actor: str) -> set[Any]:
    """The accounts an actor may act on: every account the world has for the Owner."""
    return (
        {*SITUATIONS["granted"], *SITUATIONS["foreign"]}
        if actor == "owner"
        else set(actor_grants(actor))
    )


def expect(key: str, actor: str, at: str) -> str:
    row = rows()[key]
    if actor == "unauthenticated":
        return "401" if key.startswith("GET ") else "csrf"
    if not set(row["permissions"]) <= _permissions(actor):
        assert row["outcomes"][actor] == "403", key  # the row and the contract agree
        return "role"
    if row["outcomes"][actor] == "403":  # permitted: step 2 refuses the account the body names
        assert key in NAMED, key
        return "scope"
    if set(SITUATIONS[at]) <= held(actor):
        return "allow"
    if key in LISTS or key in NAMED:
        return "scope"
    return "missing" if at == "absent" else "foreign"


def cells() -> list[Cell]:
    return [
        Cell(key, actor, at, expect(key, actor, at))
        for key in sorted(rows("executed"))
        for actor in ACTORS
        for at in situations(key)
    ]


def ws_outcomes(topic: str) -> dict[str, str]:
    """A `topics` row: each actor's `sub` outcome."""
    outcomes: dict[str, str] = matrix()["topics"][topic]["outcomes"]
    return outcomes
