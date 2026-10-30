"""E28-X03 (#976): every E28 route x every role x every scope situation, three properties a cell.

R3 exit criterion #10: a disallowed cell asserts its status and problem code, that no store of the
world changed (a walk of every fake store, table, notice list and cache, before and after: a
refusal that wrote first is still a breach, whichever store it wrote), and its audit, looked up by
the request's own id (`X-Correlation-Id`, bound by the middleware, #3990): one `rbac.denied` naming
the caller for a 403, and none at all for the anti-enumeration 404, which must answer as a missing
object does (PF-I06, SR-E28-21). A 404 reads in the caller's scope, so its read logs are left out
of the walk; nothing else is. An allowed cell is not refused (no 401, no RBAC or scope 403, no
`rbac.denied`) and answers below 500. No cell's answer names an account the caller does not hold.
Parametrised by route, so the matrix shards (`-k`). No network, no sleeps (C-13.5, C-13.7).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.contract.rbac.rbac_harness import (
    ABSENT,
    FOREIGN,
    GRANTED,
    actor_grants,
    bearer,
    observed,
)
from tests.contract.rbac.rbac_harness import user_id_of as uid
from tests.contract.test_account_profile_reads_provider import Store as Profiles
from tests.contract.test_account_profile_writes_provider import _ALT, _RISK
from tests.security.e28 import _cells as cells
from tests.security.e28._world import (
    DEFINITION,
    GROUP,
    READ_LOGS,
    SITUATIONS,
    E28World,
    request_id,
    state,
)
from tests.unit.api.test_trade_group_definition_create import payload
from tests.unit.api.test_trade_group_preview_route import body as preview_body

_SEEDED = Profiles().rows
#: The profile each account's cells name: GRANTED's "Alt" and FOREIGN's one; an Owner reads both.
_PROFILE = {account: rows[-1] for account, rows in _SEEDED.items() if rows}
_RBAC_CODES = frozenset({"forbidden", "account_scope_denied"})
#: What each refusal records under the request's id: nothing for a caller with no principal and
#: for the anti-enumeration 404 (a record would be the oracle), else the guard's own record.
_AUDITED = {
    "401 unauthenticated": [], "404 not_found": [], "403 csrf_token_invalid": ["auth.csrf_refused"],
    "403 forbidden": ["rbac.denied"],
    "403 account_scope_denied": ["rbac.denied", "trade_group.previewed"],
}  # fmt: skip


def _sent(cell: cells.Cell) -> tuple[str, Any, dict[str, str]]:
    """The cell's path, body and headers, well formed: a refusal is the cell's, not the body's."""
    method, template = cell.key.split(" ", 1)
    accounts = SITUATIONS[cell.at]
    account = accounts[0] if accounts else GRANTED
    row = _PROFILE[account]
    path = template.format(
        accountId=account, profileId=row.id, tradeGroupId=GROUP.get(cell.at),
        definitionId=DEFINITION.get(cell.at),
    )  # fmt: skip
    headers: dict[str, str] = {}
    sent: Any = None
    if template.endswith("{profileId}") and method != "GET":
        headers["if-match"] = f'W/"{row.id}:{row.version}"'
        sent = _ALT if method == "PUT" else None
    elif template.endswith("/profiles") and method == "POST":
        sent = _RISK
    elif template.endswith("/default-profile") and method == "PUT":
        sent, headers["if-match"] = {"profile_id": str(row.id)}, f'W/"{account}:default:1"'
    elif cell.key == cells.PREVIEW:
        sent = preview_body(*accounts)
    elif template.startswith("/trade-group-definitions") and method in ("POST", "PUT"):
        sent = payload(*accounts, name="E28 written")
    return path, sent, headers


def _send(world: E28World, cell: cells.Cell) -> Any:
    path, sent, headers = _sent(cell)
    headers |= {**bearer(cell.actor), "X-Correlation-Id": request_id(cell.id)}
    method = cell.key.split(" ", 1)[0]
    return world.writes.world.client.request(method, path, json=sent, headers=headers)


def _refused(resp: Any, written: list[dict[str, Any]]) -> bool:
    code = observed(resp).partition(" ")[2]
    denied = any(r["action"] == "rbac.denied" for r in written)
    return resp.status_code == 401 or (resp.status_code == 403 and code in _RBAC_CODES) or denied


def _ungranted(actor: str) -> set[str]:
    held = set() if actor == "owner" else {GRANTED, FOREIGN} - set(actor_grants(actor))
    return {str(a) for a in held}


@pytest.mark.parametrize("cell", [pytest.param(c, id=c.id) for c in cells.cells()])
def test_every_e28_cell_is_answered_as_the_matrix_and_the_scope_rule_say(
    world: E28World, cell: cells.Cell
) -> None:
    skip = READ_LOGS if cell.expect.startswith("404") else frozenset[str]()
    before, logged = state(world.stores(), skip=skip), len(world.records)
    resp = _send(world, cell)
    after, written = state(world.stores(), skip=skip), world.by_request.get(request_id(cell.id), [])
    assert len(world.records) - logged == len(written), "a record without the request's own id"
    leaked = [a for a in _ungranted(cell.actor) if a in resp.text]
    assert not leaked, f"{cell.id}: the answer names an account the caller does not hold"
    actions = [(r["action"], r.get("outcome")) for r in written]
    if not cell.denied:
        assert not _refused(resp, written), f"{cell.id}: refused ({observed(resp)}, {actions})"
        assert resp.status_code < 500, f"{cell.id}: {observed(resp)}"
        return
    assert observed(resp) == cell.expect, cell.id
    assert after == before, f"{cell.id}: a refused call changed a store"
    assert [a for a, _ in actions] == _AUDITED[cell.expect], f"{cell.id}: {actions}"
    if cell.expect.startswith("403 ") and cell.expect != "403 csrf_token_invalid":
        assert (actions[0][1], str(written[0]["actor_user_id"])) == ("denied", str(uid(cell.actor)))


_READS = sorted(k for k in cells.rows("executed") if k.startswith("GET ") and "Id}" in k)
_SAME = ("content-type", "content-length", "etag", "cache-control")


@pytest.mark.parametrize("key", _READS)
def test_an_ungranted_object_is_answered_byte_for_byte_as_an_absent_one(
    world: E28World, key: str
) -> None:
    """PF-I06, AC-06: the 404 for an object outside the caller's grants is the 404 for one that
    does not exist: the same status, the same body and the same headers, so no field differs."""
    path = key.split(" ", 1)[1]
    absent = path.format(
        accountId=ABSENT, profileId=uuid.UUID(int=0xAB5E), tradeGroupId=uuid.UUID(int=0xAB5E),
        definitionId=uuid.UUID(int=0xAB5E),
    )  # fmt: skip
    foreign = _sent(cells.Cell(key, "manager_with_grant", "foreign", "404 not_found"))[0]
    got = [
        world.writes.world.client.get(p, headers=bearer("manager_with_grant"))
        for p in (foreign, absent)
    ]
    assert [r.status_code for r in got] == [404, 404]
    assert got[0].content == got[1].content
    assert [{h: r.headers.get(h) for h in _SAME} for r in got] == [
        {h: got[1].headers.get(h) for h in _SAME}
    ] * 2
