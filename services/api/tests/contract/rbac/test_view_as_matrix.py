"""#3085 S9 (plan section 4, item 5): an Owner viewing as a user reads exactly what that user reads.

Every executed `GET` row of `matrix.yaml` is sent twice in the same world: on the target's own
session, and on the Owner's session while it holds a live view-as context on that target. The two
answers must be the same, status, problem code and body, and match the target's reviewed outcome.
`GET /me` differs in one field, by ruling (Q10): it names the session asking, the viewer's.
The view-as guard stamps the target as a live read's subject, and every resolver answers in the
subject's scope (`api/view_as_subject.py`), so the Owner's own grants, permissions and data never
reach the read. The viewer's own reads (`OWN_OPERATIONS`) answer as the Owner. The world is
`test_route_matrix.py`'s: the real app with the identity and backend seams faked, no network
(C-13.5).
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from candleviewer.api.view_as_policy import OWN_OPERATIONS
from tests.contract.rbac.rbac_harness import (
    MATRIX_PATH,
    VIEW_TARGETS,
    World,
    bearer,
    bearer_viewing,
    fill_path,
    session_id_of,
)

with MATRIX_PATH.open(encoding="utf-8") as _fh:
    _OPS: dict[str, dict[str, Any]] = yaml.safe_load(_fh)["operations"]


def _executed_reads(*, own: bool) -> tuple[str, ...]:
    return tuple(
        key
        for key, row in _OPS.items()
        if row["state"] == "executed"
        and key.startswith("GET ")
        and (("GET", key.split(" ", 1)[1]) in OWN_OPERATIONS) is own
    )


#: Every executed read but the viewer's own, by matrix key.
_READS = _executed_reads(own=False)
#: The viewer's own reads: they act on the viewer's session, as the viewer.
_OWN_READS = _executed_reads(own=True)


def _get(client: TestClient, key: str, headers: dict[str, str]) -> Any:
    req = _OPS[key].get("request", {})
    return client.get(
        fill_path(key.split(" ", 1)[1], req.get("path")),
        params=req.get("params"),
        headers={**headers, **req.get("headers", {})},
    )


def _answer(resp: Any) -> tuple[int, Any]:
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, resp.text


def _as_viewed(key: str, own: tuple[int, Any], target: str) -> tuple[int, Any]:
    """The target's own answer as the viewing session must give it: `GET /me` names the viewer's
    session (Q10: the session asking, and none of the target's elevation); every other read is
    the target's, unchanged."""
    status, body = own
    if key != "GET /me" or status != 200:
        return own
    viewing = str(session_id_of("owner", viewing=target))
    return status, {**body, "session": {**body["session"], "session_id": viewing}}


def _classify(status: int) -> str:
    return {401: "401", 403: "403"}.get(status, "allow")


@pytest.mark.parametrize("target", VIEW_TARGETS)
@pytest.mark.parametrize("key", _READS)
def test_an_owner_viewing_as_a_target_reads_as_the_target(
    world: World, key: str, target: str
) -> None:
    """Plan section 4, item 5 (its `test_owner_viewing_as_actor_reads_like_actor`)."""
    own = _as_viewed(key, _answer(_get(world.client, key, bearer(target))), target)
    viewing = _answer(_get(world.client, key, bearer_viewing(target)))
    assert viewing == own, f"{key} viewed as {target}: {viewing} differs from its own {own}"


#: Each read and target whose outcome the matrix has reviewed (no `pending` row).
_REVIEWED = tuple(
    (key, target)
    for key in _READS
    for target in VIEW_TARGETS
    if target not in _OPS[key].get("pending", {})
)


@pytest.mark.parametrize(("key", "target"), _REVIEWED)
def test_an_owner_viewing_as_a_target_gets_the_targets_reviewed_outcome(
    world: World, key: str, target: str
) -> None:
    status, _ = _answer(_get(world.client, key, bearer_viewing(target)))
    assert _classify(status) == _OPS[key]["outcomes"][target], key


@pytest.mark.parametrize("target", VIEW_TARGETS)
def test_some_read_refuses_the_target_and_answers_the_owner(target: str) -> None:
    """The matrix test discriminates: for every target, some read the Owner is answered refuses
    the target, so an answer in the Owner's scope fails it."""
    outcomes = [(_OPS[k]["outcomes"]["owner"], _OPS[k]["outcomes"][target]) for k in _READS]
    assert ("allow", "403") in outcomes


@pytest.mark.parametrize("target", VIEW_TARGETS)
@pytest.mark.parametrize("key", _OWN_READS)
def test_the_viewers_own_reads_answer_as_the_viewer(world: World, key: str, target: str) -> None:
    status, body = _answer(_get(world.client, key, bearer_viewing(target)))
    assert (status, _OPS[key]["outcomes"]["owner"]) == (200, "allow"), (key, body)
