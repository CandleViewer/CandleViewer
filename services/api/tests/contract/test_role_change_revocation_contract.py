"""Role-change revocation contract (SR-013, #2101; the #2101 ruling's C-1 to C-3).

A change to a user's role set, by `setUserRoles` or by `updateUser` with `roles`, revokes every
live session of the user (C-1): the target sees `401 unauthenticated`, then
`401 refresh_token_invalid`, and its sockets close `4401` with `bye session_revoked`, published for
every member of each revoked session's rotation family (C-3). The actor's own sessions are never
touched, and a refused or no-op call revokes nothing. Each revocation is audited write-ahead as
`auth.session_revoked` (reason `role_changed`, C-7); a store failure after the commit is
`503 store_unavailable`, naming the per-session `DELETE` as the repair. The `200` bodies do not
change, so no `!` (C-9). Account-grant changes revoke no session (C-2). This module pins the
`22-api-openapi.yaml` prose and shapes and the `23-ws-protocol.md` sentences that say so, and the
WS client row a step-up's in-place re-`auth` adds (C-3).
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from tests.contract._admin_support import ROOT

_WS = " ".join((ROOT / "docs/plan/23-ws-protocol.md").read_text(encoding="utf-8").split())


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _flat(text: str) -> str:
    """Collapse YAML line wrapping so prose pins survive a re-wrap."""
    return " ".join(text.split())


def _described(spec: dict[str, Any], method: str, path: str) -> str:
    return _flat(spec["paths"][path][method]["description"])


@pytest.mark.parametrize(
    "rule",
    [
        "A change to the user's role set revokes every live session of the user, on every device",
        "the user's next REST request is answered `401 unauthenticated`, `POST /auth/refresh` "
        "with its refresh token `401 refresh_token_invalid`",
        "each socket on one of those sessions, or on an older session of its rotation family, "
        "gets `bye` with `session_revoked` and closes `4401`",
        "The user signs in again, and the new session carries the new roles.",
        "The caller's own sessions are never touched (a self-target is refused above)",
        "a call that is refused or changes no role revokes nothing",
        "Each revocation is audited as `auth.session_revoked` (reason `role_changed`), written "
        "ahead with the role change: when one cannot be written nothing changes "
        "(`503 audit_unavailable`).",
        "the answer is `503 store_unavailable`: the new roles stand, and each remaining session "
        "of the user is revoked with `DELETE /users/{userId}/sessions/{sessionId}`",
        "The `200` body is unchanged.",
        # C-8: an in-flight request keeps its entry authority (#2593 re-checks at the effect); the
        # refresh and rotation window is accepted and documented. Unlike a disable's, nothing
        # re-reads its survivor, which carries the new role set.
        "A request of the user already authorised when the change lands completes on the "
        "authority it had at entry",
        "a refresh or a step-up rotation of the user in flight across the revocation can mint a "
        "successor that survives it",
        "unlike a disable, whose mint refuses the user and whose next request ends such a "
        "survivor, a role change changes nothing the mint or a request re-reads. The survivor "
        "carries the new role set.",
    ],
)
def test_set_user_roles_states_the_session_revocation(spec: dict[str, Any], rule: str) -> None:
    assert rule in _described(spec, "put", "/users/{userId}/roles")


def test_update_user_revokes_on_a_role_change_as_set_user_roles_does(
    spec: dict[str, Any],
) -> None:
    text = _described(spec, "patch", "/users/{userId}")
    assert (
        "A change to the user's role set (`roles`) revokes every live session of the user exactly "
        'as `setUserRoles` describes ("Sessions", SR-013, #2101)'
    ) in text


@pytest.mark.parametrize(
    ("method", "path"), [("put", "/users/{userId}/roles"), ("patch", "/users/{userId}")]
)
def test_role_change_operations_answer_both_503s(
    spec: dict[str, Any], method: str, path: str
) -> None:
    """The write-ahead refusal and the post-commit store failure are both `ServiceUnavailable`,
    whose examples cover `store_unavailable`."""
    responses = spec["paths"][path][method]["responses"]
    assert responses["503"] == {"$ref": "#/components/responses/ServiceUnavailable"}
    assert "store_unavailable" in str(spec["components"]["responses"]["ServiceUnavailable"])


def test_set_user_roles_ok_body_is_unchanged(spec: dict[str, Any]) -> None:
    """C-9: the actor still gets `200 {id, roles}`; no `!`."""
    ok = spec["paths"]["/users/{userId}/roles"]["put"]["responses"]["200"]
    schema = ok["content"]["application/json"]["schema"]
    assert schema["required"] == ["id", "roles"]
    assert set(schema["properties"]) == {"id", "roles"}
    assert "headers" not in ok  # no token, no cookie: the target's sessions end, nothing rotates


def test_update_user_ok_body_is_unchanged(spec: dict[str, Any]) -> None:
    ok = spec["paths"]["/users/{userId}"]["patch"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/User"}
    assert set(ok["headers"]) == {"ETag"}


@pytest.mark.parametrize(
    "sentence",
    [
        # 23 section 4.3 (:472): a role change is a published revocation, a step-up rotation is not.
        "the owner TOTP reset and a role change (every live session of the user, SR-013, #2101) "
        "all end with `bye session_revoked` + `4401`.",
        "A refresh-token rotation is not a revocation, and neither is the rotation of a "
        "successful step-up (SR-013, #2101): the socket stays open for its in-place re-`auth` "
        "with the new session's token (§4.1), and nothing is published.",
        # C-3: the straggler socket on a rotated-out session closes on a role change's publish.
        "is not closed by a revocation of the successor session, except a role change's, which "
        "publishes every member of each revoked session's rotation family (#2101).",
        # 23 section 9.5.
        "**A role change ends the user's sessions (SR-013, #2101).** A change to a user's role "
        "set (`setUserRoles`, or `updateUser` with `roles`) first revokes every live session of "
        "the user",
        "So the user's own sockets never take a role change in place: the user signs in again "
        "and authenticates under the new roles.",
        "The re-evaluation below still runs after the revocation, for the sockets that view the "
        "user from another user's session (§9.6).",
        # C-2: grant changes revoke nothing.
        "A change to account grants revokes no session (SR-013 lists role changes): it is "
        "applied in place, as below.",
        # C-3's client row: the step-up's sockets re-authenticate in place.
        "| C22 | After a successful step-up, re-`auth` every open socket in place with its new "
        "token (§4.1). |",
    ],
)
def test_ws_protocol_states_the_role_change_and_step_up_rules(sentence: str) -> None:
    assert sentence in _WS
