"""Unit (E42-T05 #966 BK-10): `POST /admin/backups/{backupId}/download` over HTTP, on the real
step-up service (`test_step_up_challenge_router`'s world). The 404, the 501s and the hourly 429
come before any challenge; each link spends one fresh `backups` code bound to its request, and its
record names that challenge, never the token. Every refusal is a `Problem` the operation lists."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from httpx import Response
from structlog.testing import capture_logs

from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.downloads import BackupDownloads, LinkRecord
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.limits import LINKS_PER_HOUR
from candleviewer.admin.backups.links import LINK_TTL, DownloadLinks
from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.api.admin_backup_links import make_admin_backup_links_router
from candleviewer.api.audit_limiter import AuditVerifyLimiter
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.storage.backup_artefacts import ArtefactUnreadable
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.backups import BackupRow
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.admin._backup_fakes import Store, row
from tests.unit.admin._link_fakes import Artefact, Reader
from tests.unit.api.test_step_up_challenge_router import _World, _world

BID, OTHER = UUID(int=1), UUID(int=2)
_OPERATION = SPEC["paths"]["/admin/backups/{backupId}/download"]["post"]
_OK = "/paths/~1admin~1backups~1{backupId}~1download/post/responses/200/content/application~1json"
_ROLES = {"owner": "backups:write", "manager": "accounts:read", "viewer": "audit:read"}


class _Principals:
    """The guard's resolver: the bearer's session, with the permission of `x-role`."""

    def __init__(self, w: _World) -> None:
        self._sessions = w.sessions

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        record = self._sessions.get(token)
        role = request.headers.get("x-role", "owner")
        if record is None:
            return None
        grant = frozenset({_ROLES[role]})
        return AuditPrincipal(record.user_id, role, grant, record.id, "10.0.0.9", UUID(int=9))


async def _mount(
    rows: Sequence[BackupRow] = (row(1),),
    *,
    store: Store | None = None,
    catalogued: bool = True,
    wired: bool = True,
    reader: Reader | None = None,
    issued_before: int = 0,
    live_max: int = 1024,
) -> tuple[_World, AuditVerifyLimiter]:
    """The world with the route mounted; `issued_before` links already count in the hour."""
    w = await _world()
    app = cast(FastAPI, w.client.app)
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    held = (Store(rows) if store is None else store) if catalogued else None
    catalogue = BackupCatalogue(held, now=w.clock)
    links, gate = DownloadLinks(now=w.clock, live_max=live_max), BackupJobGate()
    service = BackupDownloads(catalogue, reader or Reader(), links, gate=gate, audit=w.audit)
    limit = AuditVerifyLimiter(rate_per_hour=LINKS_PER_HOUR, clock=lambda: 0.0)
    for _ in range(issued_before):
        limit.record_start(_owner(w))
    app.include_router(
        make_admin_backup_links_router(
            catalogue, service if wired else None, auth=w.auth, resolver=_Principals(w),
            audit=w.audit, limit=limit,
        )
    )  # fmt: skip
    return w, limit


def _owner(w: _World) -> str:
    return str(w.sessions["tok"].user_id)


def _post(w: _World, backup: UUID = BID, role: str = "owner") -> Response:
    headers = {"Authorization": "Bearer tok", "x-role": role}
    sent: Response = w.client.post(f"/admin/backups/{backup}/download", headers=headers)
    return sent


def _issue(w: _World, backup: UUID = BID) -> tuple[dict[str, Any], Response]:
    """The challenge a first request gets, a step-up answering it, and the request again."""
    challenge: dict[str, Any] = _post(w, backup).json()
    assert challenge["code"] == "step_up_required", challenge
    w.clock.now += timedelta(seconds=30)  # a fresh TOTP step: a code is good once
    assert w.step_up(challenge_id=challenge["challenge_id"]).status_code == 200
    return challenge, _post(w, backup)


def _refused(response: Response, status: int, code: str) -> dict[str, Any]:
    body: dict[str, Any] = response.json()
    assert (response.status_code, body["code"]) == (status, code), body
    assert response.headers["content-type"] == "application/problem+json"
    assert str(status) in _OPERATION["responses"]
    validate_example("/components/schemas/Problem", body)
    return body


def _records(w: _World) -> list[dict[str, Any]]:
    return w.of("backup.downloaded")


async def test_issue_spends_one_fresh_backups_code_per_link() -> None:
    w, _ = await _mount()
    first, issued = _issue(w)
    assert issued.status_code == 200
    again = _refused(_post(w), 403, "step_up_required")  # the grant is gone with its link
    assert again["action_class"] == "backups" and again["challenge_id"] != first["challenge_id"]
    second, issued_again = _issue(w)
    assert issued_again.status_code == 200 and issued.json() != issued_again.json()
    spent = [r["after_state"]["challenge_id"] for r in _records(w)]
    assert spent == [first["challenge_id"], second["challenge_id"]]


async def test_a_grant_bound_to_another_backup_is_a_mismatch_and_stays_bound() -> None:
    w, _ = await _mount([row(1), row(2)])
    challenge = _post(w, BID).json()
    w.clock.now += timedelta(seconds=30)
    assert w.step_up(challenge_id=challenge["challenge_id"]).status_code == 200
    _refused(_post(w, OTHER), 403, "step_up_required")  # backup 1's grant, for backup 2
    (mismatch,) = w.of("auth.step_up_mismatch")
    assert mismatch["object_id"] == challenge["challenge_id"] and _records(w) == []
    assert _post(w, BID).status_code == 200  # still bound to backup 1's request
    assert [r["object_id"] for r in _records(w)] == [str(BID)]


async def test_unknown_backup_is_404_before_any_challenge() -> None:
    w, _ = await _mount([row(2)])
    _refused(_post(w, BID), 404, "not_found")
    assert w.of("auth.step_up_required") == [] and _records(w) == []


@pytest.mark.parametrize(
    ("setup", "status", "code"),
    [({"catalogued": False}, 501, "not_implemented"), ({"wired": False}, 501, "not_implemented"),
     ({"store": Store(error=StorageTierUnavailable("down"))}, 503, "store_unavailable")],
    ids=["no-catalogue", "no-artefact-store", "catalogue-down"],
)  # fmt: skip
async def test_unwired_is_501_before_any_challenge(
    setup: dict[str, Any], status: int, code: str
) -> None:
    w, _ = await _mount(**setup)
    _refused(_post(w), status, code)
    assert w.of("auth.step_up_required") == [] and _records(w) == []


async def test_eleventh_link_in_an_hour_is_429_before_any_challenge() -> None:
    w, limit = await _mount(issued_before=LINKS_PER_HOUR - 1)
    assert _issue(w)[1].status_code == 200  # the tenth
    challenged = len(w.of("auth.step_up_required"))
    eleventh = _post(w)
    body = _refused(eleventh, 429, "rate_limited")
    assert eleventh.headers["retry-after"] == "3600" == str(body["retry_after_seconds"])
    assert len(w.of("auth.step_up_required")) == challenged and len(_records(w)) == 1
    assert limit.retry_after(_owner(w)) == 3600  # the refused check took no place, so frees none


async def test_unusable_backup_is_409_after_the_spend_and_recorded_as_failure() -> None:
    w, limit = await _mount([row(1, status="failed")], issued_before=LINKS_PER_HOUR - 1)
    challenge, refused = _issue(w)
    body = _refused(refused, 409, "conflict")
    assert [e["rule"] for e in body["errors"]] == ["backup_not_usable"]
    (record,) = _records(w)
    assert (record["outcome"], record["reason"]) == (AuditOutcome.FAILURE, "backup_not_usable")
    assert record["after_state"] == {"stage": "issued", "challenge_id": challenge["challenge_id"]}
    _refused(_post(w), 403, "step_up_required")  # the grant was spent
    assert limit.retry_after(_owner(w)) is None  # the refused tenth freed its place


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        ("audit", "audit_unavailable"),
        ("volume", "store_unavailable"),
        ("full", "store_unavailable"),
    ],
)
async def test_an_outage_after_the_spend_is_503_and_the_grant_stays_spent(
    fault: str, code: str
) -> None:
    reader = Reader(error=ArtefactUnreadable()) if fault == "volume" else None
    w, _ = await _mount(reader=reader, live_max=0 if fault == "full" else 1024)
    if fault == "audit":
        w.audit.fail_on = frozenset({"backup.downloaded"})
    _, refused = _issue(w)
    assert _refused(refused, 503, code)["retry_after_seconds"] == 5
    assert len(_records(w)) == (0 if fault == "audit" else 1)
    _refused(_post(w), 403, "step_up_required")


async def test_issued_record_names_the_challenge_and_never_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passed: list[LinkRecord] = []
    audit_issue = BackupDownloads.audit_issue

    async def spy(self: BackupDownloads, who: AuditPrincipal, record: LinkRecord) -> None:
        passed.append(record)
        await audit_issue(self, who, record)

    monkeypatch.setattr(BackupDownloads, "audit_issue", spy)
    w, _ = await _mount()
    with capture_logs() as logs:
        challenge, issued = _issue(w)
    assert [entry.link is not None for entry in passed] == [True]  # the service's own writer
    token = issued.json()["download_url"].rsplit("/", 1)[1]
    (record,) = _records(w)
    assert record["after_state"]["challenge_id"] == challenge["challenge_id"]  # BK-1 F3
    assert (record["outcome"], record["severity"]) == (AuditOutcome.SUCCESS, Severity.ERROR)
    assert (record["object_kind"], record["object_id"]) == ("backup", str(BID))
    assert set(record["after_state"]) == {"stage", "challenge_id", "link_id", "expires_at"}
    assert token not in f"{w.audit.calls}{logs}"


async def test_response_is_no_store_and_the_url_is_the_relative_api_path() -> None:
    w, _ = await _mount()
    _, issued = _issue(w)
    body = issued.json()
    assert issued.headers["cache-control"] == "no-store"
    assert set(body) == {"download_url", "expires_at"}
    fetch = rf"/api/v1/admin/backups/{BID}/download/[A-Za-z0-9_-]{{43}}"
    assert re.fullmatch(fetch, body["download_url"])
    assert body["expires_at"] == (w.clock.now + LINK_TTL).isoformat()
    validate_example(f"{_OK}/schema", body)
    challenge = _refused(_post(w), 403, "step_up_required")
    summary = f"Issue a 5-minute download link for backup '{BID}' (pg_dump)"
    assert (challenge["action_summary"], challenge["target"]) == (summary, None)


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_manager_and_viewer_get_403_never_a_challenge(role: str) -> None:
    w, _ = await _mount()
    _refused(_post(w, role=role), 403, "forbidden")
    (entered,) = w.audit.calls
    assert (entered["action"], entered["outcome"]) == ("admin.area_entered", AuditOutcome.DENIED)
    assert entered["reason"] == "missing_permission:backups:write"


def test_the_routes_own_limit_is_ten_links_an_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[int] = []

    def limiter(*, rate_per_hour: int) -> AuditVerifyLimiter:
        built.append(rate_per_hour)
        return AuditVerifyLimiter(rate_per_hour=rate_per_hour)

    monkeypatch.setattr("candleviewer.api.admin_backup_links.AuditVerifyLimiter", limiter)
    unused: Any = None  # nothing is called while the router is built
    make_admin_backup_links_router(
        BackupCatalogue(None), None, auth=unused, resolver=None, audit=unused
    )
    assert built == [LINKS_PER_HOUR] == [10]


async def test_a_link_in_flight_holds_its_place_until_its_answer() -> None:
    w: _World
    seen: list[int | None] = []

    class Probe(Reader):  # another issue, arriving while the tenth is in flight
        async def resolve(self, location: str) -> Artefact:
            seen.append(limit.retry_after(_owner(w)))
            return await super().resolve(location)

    w, limit = await _mount(reader=Probe(), issued_before=LINKS_PER_HOUR - 1)
    assert _issue(w)[1].status_code == 200 and seen == [3600]


async def test_a_request_in_the_step_up_gate_holds_its_place_and_an_error_there_frees_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The place is taken at the check, so a concurrent check finds it held while this request is
    in the gate (SR-BK10B-01). The session store down there is the app's redacted 500 (as on the
    purge route; no link is issued), and the place is freed."""
    w, limit = await _mount(issued_before=LINKS_PER_HOUR - 1)
    held: list[int | None] = []

    async def down(*_args: Any, **_kwargs: Any) -> Any:
        held.append(limit.retry_after(_owner(w)))  # a concurrent check, the tenth in flight
        raise StorageTierUnavailable("down")

    monkeypatch.setattr(w.auth.step_up, "consume_single_use", down)
    with pytest.raises(StorageTierUnavailable):
        _post(w)
    assert held == [3600] and _records(w) == [] and limit.retry_after(_owner(w)) is None
