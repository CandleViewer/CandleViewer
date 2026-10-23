"""The cells of the E42-X03 admin RBAC suite (#1026).

Every `/admin*` and `/users*` route the route matrix runs, for every matrix actor in every
elevation state (none, stale, fresh; see `_world.py`). Each cell asserts the status and problem
`code`, the audit record and the denial count. The expectations come from three reviewed sources
and no fourth list:

1. The role outcome: `tests/contract/rbac/matrix.yaml`, Security-owned, read and never edited here.
   `test_route_matrix.py` already fails when the app serves a route with no row.
2. The step-up gate: `DANGEROUS_ROUTES` is path-gated (the guard runs before RBAC, so any session
   without the class is challenged) and `HANDLER_GATED_ROUTES` is gated by the handler after RBAC
   (`api/step_up.py`). Their contract sweep (`tests/unit/api/test_dangerous_route_registry.py`)
   already fails a mounted step-up operation missing from them.
3. The guard kind: a route on `admin_router` (found by its `admin_area` dependency) denies with
   `admin.area_entered`, outcome `denied`, naming the route. Every other admin or users route is in
   `OWN_GUARD`, with the record its own guard writes. A route in neither fails
   `test_every_admin_route_is_classified`.

The executed rows are the cells. Of the two served `not_executable` rows, `PATH_GATED_ONLY` gives
`rewrapKek` its none and stale cells, which its path guard answers before any body is read, and
`NO_CELL` says why `PUT /admin/log-level` has none.

The rules the cells hold:

- A denial (403 `forbidden`) writes its record for the caller and adds one to
  `authz_denied_total{permission}` (SR-125, the ticket's Observability: a silent denial fails).
- A step-up challenge (403 `step_up_required`) is a challenge, not a denial (decision D6 on #1026):
  it is audited as `auth.step_up_required` naming its class. No denial counter is asserted for it.
- An allowed call on `admin_router` writes `admin.area_entered`, outcome `success`, and a call let
  through by a grace window writes `auth.step_up_grace_used` naming the class. An allowed call on
  an own-guard route asserts no record: with the matrix's bodies most answer 4xx or 501 before
  acting, so the action records of those routes rest on their own tests until #2836 moves them
  onto `admin_router` (SR-E42-09).
- Elevation never stands in for a permission: a manager or viewer holding every grace window is
  still refused wherever the matrix refuses it.
- A handler that answers before its gate in the app as wired today is listed in `BEFORE_GATE`
  with that answer's status and its reason; its allowed caller must get that status, so a
  challenge or any other answer fails the cell.
- A route the matrix makes public (BK-11's fetch, whose token is the credential) runs for every
  caller, the one with no session included.

What the cells do not assert: that state is unchanged after a denial (the cells read statuses and
records; the abuse cases check stores where the seed says so), and a record or a count for the
401 or CSRF refusal of a caller with no session, which has no principal to record (AC-ADM-02).

Known gaps are `xfail(strict=True, raises=AssertionError)`, never skipped, so each turns red the
day it is fixed and a harness error never passes as one (D11):

- `#2836` (SR-E42-09): own guards that count no denial or carry no `code`, and
  `GET /admin/support-bundle/{job_id}`, which refuses with no record at all.
- AD-F24 (e42-admin.md §13.1): a 401 whose `code` is not the registry's `unauthenticated`. The
  model owns it on `#2304` for the step-up router (`api/users.py`'s half was met by #2649); the
  invites router's 401, which carries no `code` at all, has no issue (finding X03-F6 in the
  catalogue).

The abuse cases that wait on other tickets are listed in `test_admin_abuse_cases.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

import httpx
import pytest
import yaml

from candleviewer.api.step_up import HANDLER_GATED_ROUTES, dangerous_action_class
from candleviewer.auth.step_up import NO_GRACE_ACTION_CLASSES, SINGLE_USE_WINDOW
from tests.contract.rbac.rbac_harness import MATRIX_PATH, fill_path, user_id_of
from tests.security.admin._world import SIGNED_IN, UNAUTHENTICATED, AdminWorld, denials

STATES = ("none", "stale", "fresh")
ADMIN_PREFIXES = ("/admin", "/users")
_UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_SR_E42_09 = "#2836 (SR-E42-09)"


@dataclass(frozen=True)
class OwnGuard:
    """A route that is not on `admin_router`: the record its refusal writes (None: none at all),
    whether the refusal is counted in `authz_denied_total`, and why the route guards itself."""

    record: str | None
    counted: bool
    why: str


_ENFORCE = OwnGuard(
    "rbac.denied", True, "the users routers deny through `auth.scopes.enforce` (C-12.4)"
)
_AUDIT_READ = OwnGuard(
    "admin.audit_denied",
    False,
    "the budgeted audit-read guard (`audit/access.py`, SR-067); joins the admin guard by #2836",
)
_RECORDER = "E16's recorder administration; `recording:write`, Managers included (04 row 51)"

#: Every served admin or users route that is not on `admin_router`. Reviewed data: SR-E42-09 wants
#: it to shrink to the users routers. The two `not_executable` matrix rows are classified too.
OWN_GUARD: dict[str, OwnGuard] = {
    "POST /users": _ENFORCE,
    "GET /users/invites": _ENFORCE,
    "POST /users/{userId}/invite": _ENFORCE,
    "DELETE /users/{userId}/invite": _ENFORCE,
    "PUT /users/{userId}/roles": _ENFORCE,
    "GET /users/{userId}/account-access": _ENFORCE,
    "PUT /users/{userId}/account-access": _ENFORCE,
    "DELETE /users/{userId}": _ENFORCE,
    "GET /users/{userId}/mfa/reset-preview": _ENFORCE,
    "POST /users/{userId}/mfa/reset": _ENFORCE,
    # E42-T09 (#2649, #3873): `make_user_admin_router` authorises each through `enforce` too.
    "GET /users/{userId}": _ENFORCE,
    "PATCH /users/{userId}": _ENFORCE,
    "GET /users/{userId}/sessions": _ENFORCE,
    "DELETE /users/{userId}/sessions/{sessionId}": _ENFORCE,
    "POST /admin/keys/kek-rewrap": OwnGuard(
        "rbac.denied", True, "#2266 D2: `enforce`, its body validated before RBAC"
    ),
    "GET /admin/audit": _AUDIT_READ,
    "POST /admin/audit/verify": _AUDIT_READ,
    "POST /admin/audit/export": _AUDIT_READ,
    "GET /admin/audit/exports/{jobId}": _AUDIT_READ,  # #889 S9, its refusals in the same budget
    "POST /admin/support-bundle": OwnGuard(
        "health.diagnostics_exported", False, "E04's diagnostics export"
    ),
    "GET /admin/support-bundle/{job_id}": OwnGuard(None, False, "E04's diagnostics export"),
    "PUT /admin/log-level": OwnGuard(
        "settings.change", False, "E04; 501 until a principal resolver is wired"
    ),
    "POST /admin/recorder/import": OwnGuard("recorder.import", False, _RECORDER),
    "POST /admin/recorder/compact": OwnGuard("recorder.compact", False, _RECORDER),
    "POST /admin/recorder/purge": OwnGuard(
        "retention.purge", False, "E16; RBAC, then owner-only, then step-up (04 row 9a)"
    ),
    "GET /admin/backups/{backupId}/download/{token}": OwnGuard(
        "backup.downloaded",
        False,
        "#966 BK-11: public in the matrix; the single-use token in the path is the credential",
    ),
}

_START = "POST /admin/view-as"
#: Requests that reach a handler-gated route's step-up gate. The matrix's empty bodies reach the
#: purge and download-link gates, which both gate before reading a body; a flag write is gated
#: under its row lock after validation, so its cell writes an ordinary all-roles flag.
GATE_REQUESTS: dict[str, dict[str, Any]] = {
    "PUT /admin/feature-flags/{flagKey}": {
        "path": {"flagKey": "rules.graph_editor"},
        "json": {"value": False, "reason": "E42-X03 RBAC cell"},
    },
    # #3085 S13b: a start passes its five refusals only for an active user who is neither the
    # caller nor an Owner, so the none and stale cells reach its gate (see `NO_FRESH_CELL`).
    _START: {
        "json": {
            "target_user_id": str(user_id_of("manager_with_grant")),
            "reason": "E42-X03 RBAC cell",
        },
    },
}
#: The class a handler-gated cell demands, where its route has several (`setFeatureFlag`).
GATE_CLASS: dict[str, str] = {"PUT /admin/feature-flags/{flagKey}": "flags"}
#: Handler-gated routes whose handler answers before its gate in the app as wired today, and with
#: what: the Owner is let in and must get that status, never a challenge or another answer. The
#: day the service is wired, the challenge (a 403) fails the Owner's cells until the row goes.
BEFORE_GATE: dict[str, tuple[int, str]] = {
    "DELETE /admin/backups/{backupId}": (
        501,
        "#966 BK-12: `501` before its gate until the backup engine passes a remover (#3319)",
    ),
    "GET /admin/audit/exports/{jobId}": (
        404,
        "#889 S9: the cell's job id names no job, so the requester check's `404` comes first; "
        "`test_audit_export_download.py` and `test_job_poll.py` reach the gate",
    ),
}
#: Served `not_executable` rows whose path guard answers before RBAC and before any body is read,
#: so their none and stale cells need no valid body. A live window passes the guard, so the fresh
#: state has no cell; why, as the matrix row reads it.
PATH_GATED_ONLY: dict[str, str] = {
    "POST /admin/keys/kek-rewrap": (
        "past the `keys` guard the body is validated before RBAC, so the matrix's empty body is a "
        "422 for every actor; a valid one reaches the CI app's missing credential store (403 "
        "`kek_unavailable` for the Owner). Every actor is asserted in `test_admin_kek.py` "
        "(#2266 D2)"
    ),
}
#: Served `not_executable` rows with no cell, and why none can exist.
NO_CELL: dict[str, str] = {
    "PUT /admin/log-level": (
        "mounted with no principal resolver: every signed-in caller, the Owner included, gets "
        "`501` before any guard reads a role, so no role outcome exists to assert (X03-F5); a "
        "caller with no session meets the CSRF guard first. Its guard is held by "
        "`test_log_level_override.py` (`test_endpoint_viewer_denied_and_audited`)"
    ),
}


@dataclass(frozen=True)
class Gate:
    where: Literal["path", "handler"]
    action_class: str

    @property
    def grace(self) -> bool:
        return self.action_class not in NO_GRACE_ACTION_CLASSES


@dataclass(frozen=True)
class Op:
    key: str
    method: str
    path: str
    permission: str
    outcomes: dict[str, str]
    request: dict[str, Any]
    gate: Gate | None
    own: OwnGuard | None  # None: on `admin_router`

    @property
    def target(self) -> str:
        return fill_path(self.path, self.request.get("path"))


def matrix_rows() -> dict[str, dict[str, Any]]:
    with MATRIX_PATH.open(encoding="utf-8") as fh:
        loaded: dict[str, Any] = yaml.safe_load(fh)
    rows: dict[str, dict[str, Any]] = loaded["operations"]
    return rows


def is_admin(key: str) -> bool:
    return key.split(" ", 1)[1].startswith(ADMIN_PREFIXES)


def gate_of(key: str) -> Gate | None:
    method, path = key.split(" ", 1)
    path_class = dangerous_action_class(method, fill_path(path))
    if path_class is not None:
        return Gate("path", path_class)
    classes = sorted(c for m, p, c in HANDLER_GATED_ROUTES if f"{m} {p}" == key)
    if not classes:
        return None
    return Gate("handler", GATE_CLASS.get(key, classes[0]))


def _op(key: str, row: dict[str, Any]) -> Op:
    method, path = key.split(" ", 1)
    [permission] = row["permissions"]
    request = GATE_REQUESTS.get(key, row.get("request", {}))
    return Op(
        key, method, path, permission, row["outcomes"], request, gate_of(key), OWN_GUARD.get(key)
    )


_ROWS = matrix_rows()
#: The executed admin and users rows: the cells.
OPS: tuple[Op, ...] = tuple(
    _op(k, r) for k, r in sorted(_ROWS.items()) if is_admin(k) and r["state"] == "executed"
)
#: The `PATH_GATED_ONLY` rows: cells in the none and stale states only.
GATE_ONLY_OPS: tuple[Op, ...] = tuple(_op(k, _ROWS[k]) for k in sorted(PATH_GATED_ONLY))
ALL_OPS: tuple[Op, ...] = OPS + GATE_ONLY_OPS
#: The grace classes the cells' routes demand: a "fresh" or "stale" world opens a window for each.
GRACE_CLASSES: tuple[str, ...] = tuple(
    sorted({op.gate.action_class for op in ALL_OPS if op.gate is not None and op.gate.grace})
)


#: The fresh cells (route, caller) whose allowed call would change the shared world for the rest of
#: its module, and why. Only that cell goes: the route's none and stale cells and its other
#: callers' fresh cells run (`callers_for`), and the call is pinned elsewhere.
NO_FRESH_CELL: dict[tuple[str, str], str] = {
    (_START, "owner"): (
        "#3085: an elevated Owner's start puts its session in a view-as context, read-only, which "
        "then refuses every later write of the module's Owner and answers its reads in the "
        "target's scope; the 201, its records and its notice are pinned in "
        "`tests/unit/api/test_view_as_start_route.py`, and the app's mount of the start in "
        "`tests/unit/test_view_as_wiring.py`"
    ),
}


def ops_for(state: str) -> tuple[Op, ...]:
    """The cells' routes in `state`: every executed row, and the path-gated-only rows unless
    a live window lets the request past their guard."""
    return OPS if state == "fresh" else ALL_OPS


def callers_for(op: Op, state: str) -> tuple[str, ...]:
    """The signed-in callers whose cell of `op` runs in `state`: all but `NO_FRESH_CELL`'s."""
    return tuple(a for a in SIGNED_IN if state != "fresh" or (op.key, a) not in NO_FRESH_CELL)


Kind = Literal["allow", "forbidden", "challenge"]


@dataclass(frozen=True)
class Record:
    """An audit record a cell needs from its caller. `action` "*" is any action; `route`, when
    given, is the route template the record names (`admin.area_entered`'s `object_id`)."""

    action: str
    outcome: str
    reason: str | None = None
    route: str | None = None


@dataclass(frozen=True)
class Expected:
    kind: Kind
    action_class: str | None = None
    records: tuple[Record, ...] = ()


def _challenge(gate: Gate) -> Expected:
    record = Record("auth.step_up_required", "denied", gate.action_class)
    return Expected("challenge", gate.action_class, (record,))


def _denial(op: Op) -> tuple[Record, ...]:
    if op.own is None:
        reason = f"missing_permission:{op.permission}"
        return (Record("admin.area_entered", "denied", reason, route=op.path),)
    return (Record(op.own.record or "*", "denied"),)


def expect(op: Op, actor: str, state: str) -> Expected:
    fresh = state == "fresh"
    gate = op.gate
    graced: tuple[Record, ...] = ()
    if gate is not None and gate.grace and fresh and op.key not in BEFORE_GATE:
        graced = (Record("auth.step_up_grace_used", "success", gate.action_class),)
    if gate is not None and gate.where == "path" and not fresh:
        return _challenge(gate)  # the path guard runs before RBAC
    if op.outcomes[actor] != "allow":
        before = graced if gate is not None and gate.where == "path" else ()
        return Expected("forbidden", records=before + _denial(op))
    if gate is not None and not fresh and op.key not in BEFORE_GATE:
        return _challenge(gate)
    entered = (Record("admin.area_entered", "success", route=op.path),) if op.own is None else ()
    return Expected("allow", records=graced + entered)


#: The route's own step-up records (#3990); every other `auth.step_up_*` record is the exchange's,
#: whose request (`POST /auth/step-up`) the sweeps send unstamped.
ROUTE_STEP_UP = frozenset({"auth.step_up_required", "auth.step_up_grace_used"})


def route_records(records: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    """The records of a cell's own request: all but the step-up exchange's (`ROUTE_STEP_UP`)."""
    return [
        r
        for r in records
        if not r["action"].startswith("auth.step_up") or r["action"] in ROUTE_STEP_UP
    ]


@dataclass(frozen=True)
class Observed:
    status: int
    code: str | None
    challenge_class: str | None
    records: tuple[dict[str, Any], ...]
    denied: float


def _body(resp: httpx.Response) -> dict[str, Any]:
    try:
        doc = resp.json()
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


def _bound_retry(
    world: AdminWorld, op: Op, actor: str, state: str, request: dict[str, Any], refused: str
) -> httpx.Response:
    """A no-grace route: step up for the challenge this request was refused with, then send it
    again unchanged; in the stale state, only once the one-shot grant has lapsed."""
    world.tick()  # this user's next TOTP time step
    granted = world.step_up(actor, challenge_id=refused)
    assert granted.status_code == 200, granted.text
    if state == "stale":
        world.tick(SINGLE_USE_WINDOW + timedelta(seconds=1))
    return world.send(actor, op.method, op.target, request)


_FLAG_WRITE = "PUT /admin/feature-flags/{flagKey}"


def resolved_request(world: AdminWorld, op: Op) -> dict[str, Any]:
    """The cell's request. A flag write must name the flag's `updated_at` as last read
    (`expected_updated_at`, required, E42-T03): the owner reads it from the store first."""
    if op.key != _FLAG_WRITE:
        return op.request
    listed = world.send("owner", "GET", "/admin/feature-flags", {})
    key = op.request["path"]["flagKey"]
    [item] = [i for i in listed.json()["items"] if i["key"] == key]
    return {**op.request, "json": {**op.request["json"], "expected_updated_at": item["updated_at"]}}


def source_ip(op: Op) -> str:
    """A loopback source per row for the unauthenticated caller (the anonymous refusal throttle)."""
    return f"127.0.42.{ALL_OPS.index(op) + 1}"


def observe(world: AdminWorld, op: Op, actor: str, state: str, *, cell: str = "") -> Observed:
    """What the cell's one request (or, for a no-grace class, its step-up exchange) did. Cached
    per world under `cell`, so the cell's tests read one exchange."""
    cell = cell or f"{state}|{op.key}|{actor}"
    if cell in world.observed:
        cached: Observed = world.observed[cell]
        return cached
    request = resolved_request(world, op)
    mark, before = len(world.audit.records), denials(op.permission)
    ip = source_ip(op) if actor not in SIGNED_IN else "127.0.0.1"
    resp = world.send(actor, op.method, op.target, request, source_ip=ip)
    body = _body(resp)
    if state != "none" and op.gate is not None and not op.gate.grace:
        if body.get("code") == "step_up_required":
            challenge = str(body["challenge_id"])
            resp = _bound_retry(world, op, actor, state, request, challenge)
            body = _body(resp)
    code = body.get("code")
    seen = Observed(
        resp.status_code,
        code if isinstance(code, str) else None,
        body.get("action_class") if code == "step_up_required" else None,
        tuple(world.audit.records[mark:]),
        denials(op.permission) - before,
    )
    world.observed[cell] = seen
    return seen


def _norm(value: object) -> str:
    return str(getattr(value, "value", value)).lower()


def _matches(record: dict[str, Any], want: Record, user_id: str) -> bool:
    return (
        (want.action == "*" or record["action"] == want.action)
        and str(record.get("actor_user_id")) == user_id
        and _norm(record.get("outcome")) == want.outcome
        and (want.reason is None or record.get("reason") == want.reason)
        and (want.route is None or record.get("object_id") == want.route)
    )


def _where(op: Op, actor: str, state: str) -> str:
    return f"{op.key} as {actor} ({state})"


def assert_status(world: AdminWorld, op: Op, actor: str, state: str, *, cell: str = "") -> None:
    want, seen = expect(op, actor, state), observe(world, op, actor, state, cell=cell)
    got = f"{_where(op, actor, state)}: got {seen.status} {seen.code}"
    if want.kind == "allow" and op.key in BEFORE_GATE:  # each excuse limits itself (SR-X03-3)
        status, why = BEFORE_GATE[op.key]
        assert seen.status == status, f"{got}, expected the {status} before its gate ({why})"
    elif want.kind == "allow":
        assert seen.status not in (401, 403), f"{got}, expected the route to run"
        assert seen.status < 500 or seen.status in (501, 503), f"{got}, an unhandled error"
    elif want.kind == "forbidden":  # a denial, never a challenge or a CSRF refusal
        refused = seen.status == 403 and seen.code not in ("step_up_required", "csrf_token_invalid")
        assert refused, f"{got}, expected a 403 denial"
    else:
        challenge = (seen.status, seen.code, seen.challenge_class)
        expected = (403, "step_up_required", want.action_class)
        wanted = f"expected 403 step_up_required ({want.action_class})"
        assert challenge == expected, f"{got} ({seen.challenge_class}), {wanted}"


def assert_code(world: AdminWorld, op: Op, actor: str, state: str) -> None:
    """A denial carries the registry's `code` (C-6.5): one body shape for every refusal."""
    seen = observe(world, op, actor, state)
    assert seen.code == "forbidden", f"{_where(op, actor, state)}: 403 with code {seen.code!r}"


def assert_records(world: AdminWorld, op: Op, actor: str, state: str, *, cell: str = "") -> None:
    want, seen = expect(op, actor, state), observe(world, op, actor, state, cell=cell)
    uid = str(world.actors[actor].user_id)
    missing = [r for r in want.records if not any(_matches(x, r, uid) for x in seen.records)]
    written = [
        (x["action"], _norm(x.get("outcome")), x.get("reason"), x.get("object_id"))
        for x in seen.records
    ]
    assert not missing, f"{_where(op, actor, state)}: no {missing} among {written}"


def assert_counted(world: AdminWorld, op: Op, actor: str, state: str) -> None:
    seen = observe(world, op, actor, state)
    assert seen.denied == 1, (
        f"{_where(op, actor, state)}: authz_denied_total{{permission={op.permission}}} "
        f"moved by {seen.denied}, expected 1 (SR-125)"
    )


def _xfail(reason: str) -> pytest.MarkDecorator:
    """A pinned gap: it fails as the cell's assertion does, and only so; any other error is red."""
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=reason)


def status_params(state: str) -> list[Any]:
    return [
        pytest.param(op, a, id=f"{op.key}|{a}")
        for op in ops_for(state)
        for a in callers_for(op, state)
    ]


def record_params(state: str) -> list[Any]:
    out: list[Any] = []
    for op in ops_for(state):
        for a in callers_for(op, state):
            marks = []
            silent = op.own is not None and op.own.record is None
            if silent and expect(op, a, state).kind == "forbidden":
                marks.append(_xfail(f"{_SR_E42_09}: {op.key} refuses with no audit record"))
            out.append(pytest.param(op, a, id=f"{op.key}|{a}", marks=marks))
    return out


def counted_params(state: str) -> list[Any]:
    out: list[Any] = []
    for op in ops_for(state):
        for a in callers_for(op, state):
            if expect(op, a, state).kind != "forbidden":
                continue
            marks = []
            if op.own is not None and not op.own.counted:
                marks.append(_xfail(f"{_SR_E42_09}: {op.key}'s own guard counts no denial"))
            out.append(pytest.param(op, a, id=f"{op.key}|{a}", marks=marks))
    return out


_NO_CODE = f"{_SR_E42_09}: its own guard refuses without the registry `code` (C-6.5)"
#: (route, actor or "*") whose denial carries no `code`, found by the suite's own red run. Each
#: own-guard `_problem` adds a `code` only when given one: the `create` and `status` handlers of
#: `make_support_bundle_router`, the `import_archive` and `compact` handlers of
#: `make_recorder_admin_router`, and the RBAC refusal of `make_recorder_purge_router`'s `denied`
#: (its owner-only refusal has `forbidden`).
CODE_GAPS: dict[tuple[str, str], str] = {
    ("POST /admin/support-bundle", "*"): _NO_CODE,
    ("GET /admin/support-bundle/{job_id}", "*"): _NO_CODE,
    ("POST /admin/recorder/import", "*"): _NO_CODE,
    ("POST /admin/recorder/compact", "*"): _NO_CODE,
    ("POST /admin/recorder/purge", "viewer"): _NO_CODE,
}
_AD_F24 = "AD-F24 (e42-admin.md §13.1, note 6): the 401 `code` is not the registry's"
#: Routes whose 401 `code` is not the registry's `unauthenticated`, and why.
UNAUTHENTICATED_CODE_GAPS: dict[str, str] = {
    "GET /admin/support-bundle/{job_id}": (
        f"{_SR_E42_09}: no `code` (`make_support_bundle_router`'s `status`)"
    ),
    "GET /users/invites": (
        f"{_AD_F24}: no `code` (`make_invites_router`'s `_owner`); no issue tracks it: AD-F24's "
        "owners name `api/users.py` (#2649, met) and `api/step_up.py` (#2304), so the "
        "catalogue records it as X03-F6 under the filing freeze"
    ),
    "GET /users/{userId}/mfa/reset-preview": (
        f"{_AD_F24}: `unauthorized` (`make_step_up_router`'s `_session`), #2304"
    ),
}


def _code_gap(op: Op, actor: str) -> str | None:
    return CODE_GAPS.get((op.key, actor)) or CODE_GAPS.get((op.key, "*"))


def code_params(state: str) -> list[Any]:
    out: list[Any] = []
    for op in ops_for(state):
        for a in callers_for(op, state):
            if expect(op, a, state).kind != "forbidden":
                continue
            gap = _code_gap(op, a)
            marks = [_xfail(gap)] if gap else []
            out.append(pytest.param(op, a, id=f"{op.key}|{a}", marks=marks))
    return out


def _public(op: Op) -> bool:
    """Public in the matrix: no session needed (BK-11's fetch, whose token is the credential)."""
    return op.outcomes[UNAUTHENTICATED] == "allow"


def unauthenticated_params() -> list[Any]:
    """Every route with cells: a caller with no session meets the same guards in any state."""
    return [pytest.param(op, id=op.key) for op in ALL_OPS]


def unauthenticated_code_params() -> list[Any]:
    """The safe-method routes that need a session: an unsafe call with no session meets the CSRF
    guard first, and a public route answers no 401."""
    out: list[Any] = []
    for op in ALL_OPS:
        if op.method in _UNSAFE or _public(op):
            continue
        gap = UNAUTHENTICATED_CODE_GAPS.get(op.key)
        marks = [_xfail(gap)] if gap else []
        out.append(pytest.param(op, id=op.key, marks=marks))
    return out


def assert_unauthenticated(world: AdminWorld, op: Op) -> None:
    """No session: 401 before any handler work. An unsafe method is refused by the CSRF guard
    first (`403 csrf_token_invalid`, SR-041), which is stricter, as the route matrix reads it.
    A route the matrix makes public runs instead."""
    seen = observe(world, op, UNAUTHENTICATED, "none")
    got = f"{op.key} with no session: got {seen.status} {seen.code}"
    if _public(op):
        assert seen.status not in (401, 403), f"{got}, expected the public route to run"
        assert seen.status < 500 or seen.status in (501, 503), f"{got}, an unhandled error"
        return
    if op.method in _UNSAFE and (seen.status, seen.code) == (403, "csrf_token_invalid"):
        return
    assert seen.status == 401, f"{got}, expected 401"


def assert_unauthenticated_code(world: AdminWorld, op: Op) -> None:
    seen = observe(world, op, UNAUTHENTICATED, "none")
    assert seen.code == "unauthenticated", f"{op.key} with no session: 401 code {seen.code!r}"
