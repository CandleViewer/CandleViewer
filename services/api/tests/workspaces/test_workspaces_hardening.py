"""#5449: the second `/workspaces*` hardening pass (E15 threat model #437, requirement wording).

SR-E15-04: a per-user write bucket on every write route (`429 rate_limited`, `Retry-After`,
counted, never queued). SR-E15-17: a workspace delete writes one `workspace.deleted` record
ahead, by ids and counts. Names drop the zero-width and BOM code points. Pane symbols are judged
by the instrument catalogue. Foreign-id denials count in `authz_denied_total` (SR-125).
The SR-E15-05 bound on soft-deleted rows is the store's, pinned in
`tests/unit/storage/test_workspaces_lock_order_unit.py` and the integration repository tests.
No sleep: the bucket's clock is fake.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.drawings_limiter import DrawingsWriteLimiter
from candleviewer.api.workspaces import WRITE_BURST, WRITES_PER_MINUTE
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.ingestion.instruments import CatalogueSnapshot
from tests._corpus import rest
from tests.workspaces._workspaces_api_env import (
    LAYOUT,
    MISSING,
    PERMS,
    USER_A,
    USER_B,
    VIEWER,
    Env,
    wire,
)

#: The recorded catalogue (as the `/watchlists` tests use it): BTCUSDT, ETHUSDT and SOLUSDT trade,
#: LUNAUSDT is closed (delisted).
_PAGE = parse_instruments(rest("rest/instruments_after.json")["result"]["list"], fetched_at_us=0)
RECORDED = CatalogueSnapshot({i.symbol: i for i in _PAGE.instruments}, 0)


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _Series:
    """A bounded-metric stand-in: records the label values of each `labels()` call."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, ...]] = []

    def labels(self, *values: str) -> _Series:
        self.seen.append(values)
        return self

    def child(self) -> _Series:
        return self

    def inc(self, amount: float = 1) -> None:
        return None

    def observe(self, value: float) -> None:
        return None


class _Metrics:
    def __init__(self) -> None:
        self.conflicts, self.layout_panes = _Series(), _Series()
        self.request_seconds, self.rate_limited = _Series(), _Series()


def _bucket(clock: _Clock) -> DrawingsWriteLimiter:
    """The shipped SR-E15-04 values on a fake clock."""
    return DrawingsWriteLimiter(per_minute=WRITES_PER_MINUTE, burst=WRITE_BURST, clock=clock)


def _layout(**over: Any) -> dict[str, Any]:
    return wire(LAYOUT | {"hotkey_slot": None} | over, "LayoutInput")


def _limited(r: Any) -> bool:
    body = r.json()
    return bool(
        r.status_code == 429
        and body["code"] == "rate_limited"
        and r.headers["Retry-After"] == str(body["retry_after_seconds"])
        and body["retry_after_seconds"] >= 1
    )


# -- SR-E15-04: the write bucket -------------------------------------------------------------


def test_workspace_writes_past_the_bucket_are_429_with_retry_after_and_counted() -> None:
    clock, metrics = _Clock(), _Metrics()
    env = Env(limiter=_bucket(clock), metrics=metrics)
    for i in range(WRITE_BURST):
        env.create(f"W{i}")
    late = env.c.post("/workspaces", json=wire({"name": "Late"}))
    assert _limited(late) and late.headers["Retry-After"] == "1"
    names = {r["name"] for r in env.c.get("/workspaces").json()["items"]}
    assert len(names) == WRITE_BURST and "Late" not in names  # refused, nothing queued
    assert metrics.rate_limited.seen == [("workspace",)]
    clock.t += 60 / WRITES_PER_MINUTE  # one token refilled
    assert env.c.post("/workspaces", json=wire({"name": "Late"})).status_code == 201
    assert len(env.c.get("/workspaces").json()["items"]) == WRITE_BURST + 1


def test_layout_writes_past_the_bucket_are_429_with_retry_after_and_counted() -> None:
    clock, metrics = _Clock(), _Metrics()
    env = Env(limiter=_bucket(clock), metrics=metrics)
    wid = env.create()["id"]
    for i in range(WRITE_BURST - 1):  # the bucket is shared by every write route
        assert (
            env.c.post(f"/workspaces/{wid}/layouts", json=_layout(name=f"L{i}")).status_code == 201
        )
    late = env.c.post(f"/workspaces/{wid}/layouts", json=_layout(name="Late"))
    assert _limited(late)
    assert len(env.c.get(f"/workspaces/{wid}/layouts").json()["items"]) == WRITE_BURST - 1
    assert metrics.rate_limited.seen == [("layout",)]


_WRITES = [
    ("POST", "/workspaces", {"name": "X"}, "WorkspaceInput"),
    ("PUT", "/workspaces/{wid}", {"name": "X"}, "WorkspaceInput"),
    ("DELETE", "/workspaces/{wid}", None, ""),
    ("POST", "/workspaces/{wid}/layouts", LAYOUT | {"hotkey_slot": None}, "LayoutInput"),
    ("PUT", "/workspaces/{wid}/layouts/{lid}", LAYOUT, "LayoutInput"),
    ("DELETE", "/workspaces/{wid}/layouts/{lid}", None, ""),
]


@pytest.mark.parametrize(("method", "path", "body", "model"), _WRITES)
def test_every_write_route_is_refused_once_the_bucket_is_empty_and_reads_are_not(
    method: str, path: str, body: dict[str, Any] | None, model: str
) -> None:
    bucket = _bucket(_Clock())
    env = Env(limiter=bucket)
    env.create("Other")
    wid = env.create()["id"]
    lid = env.make_layout(wid)["id"]
    while bucket.try_take(str(USER_A)) is None:  # drain what is left
        pass
    writes_before = len(env.repo.calls)
    r = env.c.request(method, path.format(wid=wid, lid=lid), json=body and wire(body, model))
    assert _limited(r)
    assert len(env.repo.calls) == writes_before  # refused before the store is asked
    assert env.c.get(f"/workspaces/{wid}").status_code == 200


def test_a_viewers_refused_writes_take_no_token_from_the_write_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SR-E15-04: the bucket is keyed by the caller's user id and taken after the permission
    check, so a Viewer's `403`s, more of them than the burst, spend none of that user's tokens:
    once the same user holds `workspaces:write`, a full burst of writes lands, then `429`."""
    clock, metrics = _Clock(), _Metrics()
    env = Env(limiter=_bucket(clock), metrics=metrics)
    wid = env.create("Keep")["id"]
    env.as_user(VIEWER)
    for _ in range(WRITE_BURST + 2):
        assert env.c.post("/workspaces", json=wire({"name": "V"})).status_code == 403
        assert env.c.delete(f"/workspaces/{wid}").status_code == 403
    assert metrics.rate_limited.seen == []  # refused for permission, never for the bucket
    monkeypatch.setitem(PERMS, VIEWER, {"workspaces:read", "workspaces:write"})
    for i in range(WRITE_BURST):
        assert env.c.post("/workspaces", json=wire({"name": f"V{i}"})).status_code == 201
    assert _limited(env.c.post("/workspaces", json=wire({"name": "Late"})))
    env.as_user(USER_A)  # another user's bucket: one write spent by the setup above
    assert env.c.post("/workspaces", json=wire({"name": "Mine"})).status_code == 201


# -- SR-E15-17: the delete record ------------------------------------------------------------


def test_workspace_delete_writes_one_workspace_deleted_record_by_ids_and_counts() -> None:
    env = Env()
    env.create("Keep")
    wid = env.create("Secret name")["id"]
    lids = sorted(env.make_layout(wid, name=f"L{i}", hotkey_slot=None)["id"] for i in range(2))
    env.repo.drawings_under[wid] = 3
    key = {"Idempotency-Key": "00000000-0000-4000-8000-000000000123"}
    assert env.c.delete(f"/workspaces/{wid}", headers=key).status_code == 204
    replay = env.c.delete(f"/workspaces/{wid}", headers=key)
    assert replay.status_code == 204 and replay.headers["Idempotency-Replayed"] == "true"
    (rec,) = [c for c in env.audit.calls if c["action"] == "workspace.deleted"]
    assert (rec["object_kind"], rec["object_id"], rec["actor_user_id"]) == (
        "workspace",
        wid,
        USER_A,
    )
    assert rec["before_state"] is None
    assert rec["after_state"] == {
        "layout_ids": lids, "layout_count": 2, "drawing_count": 3,
        "purged_workspaces": 0, "purged_layouts": 0,
    }  # fmt: skip
    assert "Secret name" not in repr(rec) and "L0" not in repr(rec)  # ids and counts only


def test_workspace_delete_whose_record_is_refused_is_503_and_changes_nothing() -> None:
    env = Env()
    env.create("Keep")
    wid = env.create()["id"]

    async def refuse(action: str, **_kw: Any) -> None:
        raise AuditUnavailable("audit sink refused")

    env.audit.emit = refuse  # type: ignore[method-assign]  # fault injection
    r = env.c.delete(f"/workspaces/{wid}")
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    assert r.headers["Retry-After"] == "5"
    assert env.c.get(f"/workspaces/{wid}").status_code == 200


def test_workspace_delete_whose_record_outlives_its_bound_is_503_audit_unavailable() -> None:
    """C-2.9: a record not written within the store's bound rolls the delete back and is
    answered as an audit refusal (`audit_unavailable`), not as a store outage."""
    env = Env()
    env.create("Keep")
    wid = env.create()["id"]
    env.repo.write_ahead_timeout_s = 0  # the bound elapses at the record's first await

    async def never(action: str, **_kw: Any) -> None:
        await asyncio.Event().wait()

    env.audit.emit = never  # type: ignore[method-assign]  # fault injection
    r = env.c.delete(f"/workspaces/{wid}")
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    assert r.headers["Retry-After"] == "5"
    assert env.c.get(f"/workspaces/{wid}").status_code == 200


def test_cross_user_workspace_delete_writes_no_record_and_purges_nothing() -> None:
    """D18 and SR-E15-05: user A deleting user B's workspace id is B's uniform `404`; the store
    refuses it before any stamp or write-ahead, so no `workspace.deleted` record is written and
    none of B's rows, live or soft-deleted, change (the denial is `rbac.denied`). The store-level
    purge scoping is pinned in `tests/integration/storage/test_workspaces_repository.py` (the IDOR
    matrix and `test_purge_never_touches_another_owners_rows`)."""
    env = Env().as_user(USER_B)
    env.create("Keep")
    theirs = env.create()["id"]
    lid = env.make_layout(theirs, hotkey_slot=None)["id"]
    gone = env.create("Gone")["id"]
    assert env.c.delete(f"/workspaces/{gone}").status_code == 204  # B's own soft-deleted row
    rows, layouts, deleted = dict(env.repo.rows), dict(env.repo.layouts), set(env.repo.deleted)
    records = len(env.audit.calls)
    env.as_user(USER_A)
    r = env.c.delete(f"/workspaces/{theirs}")
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    new = env.audit.calls[records:]
    assert [c["action"] for c in new] == ["rbac.denied"]
    assert (env.repo.rows, env.repo.layouts, env.repo.deleted) == (rows, layouts, deleted)
    env.as_user(USER_B)
    assert env.c.get(f"/workspaces/{theirs}/layouts/{lid}").status_code == 200


def test_layout_delete_returns_and_logs_its_early_purge_count() -> None:
    """SR-E15-05: the store answers how many soft-deleted layouts the delete purged past the
    bound, and the router logs it by count and kind (ids as the neighbouring logs, no names);
    a delete within the bound logs no purge."""
    env = Env()
    wid = env.create()["id"]
    first, second = (env.make_layout(wid, name=n, hotkey_slot=None)["id"] for n in ("L1", "L2"))
    with capture_logs() as logs:
        assert env.c.delete(f"/workspaces/{wid}/layouts/{first}").status_code == 204
        env.repo.purge_early = 3
        assert env.c.delete(f"/workspaces/{wid}/layouts/{second}").status_code == 204
    purges = [e for e in logs if e["event"] == "workspace_rows_purged_early"]
    assert len(purges) == 1
    assert {k: purges[0][k] for k in ("count", "kind", "user_id")} == {
        "count": 3, "kind": "layout", "user_id": str(USER_A),
    }  # fmt: skip
    assert "L1" not in repr(logs) and "L2" not in repr(logs)


def test_workspace_delete_logs_its_early_purges_by_kind() -> None:
    """SR-E15-05: a workspace delete logs the same event per kind it purged past the bound, so a
    search for `workspace_rows_purged_early` finds every early purge."""
    env = Env()
    env.create("Keep")
    wid = env.create()["id"]
    env.repo.purge_early_workspace = (2, 5)
    with capture_logs() as logs:
        assert env.c.delete(f"/workspaces/{wid}").status_code == 204
    purges = sorted(
        (e["kind"], e["count"]) for e in logs if e["event"] == "workspace_rows_purged_early"
    )
    assert purges == [("layout", 5), ("workspace", 2)]


# -- names: zero-width and BOM ---------------------------------------------------------------


@pytest.mark.parametrize("invisible", ["\u200b", "\u200c", "\u200d", "\ufeff"])
def test_workspace_name_with_a_zero_width_or_bom_code_point_is_stored_without_it(
    invisible: str,
) -> None:
    env = Env()
    made = env.create(f"{invisible}Scal{invisible}ping{invisible}")
    assert made["name"] == "Scalping"
    again = env.c.post("/workspaces", json=wire({"name": f"Scalping{invisible}"}))
    assert again.status_code == 409 and again.json()["errors"][0]["rule"] == "name_taken"
    only = env.c.post("/workspaces", json=wire({"name": invisible * 3}))
    assert only.status_code == 422 and only.json()["errors"][0]["rule"] == "string_too_short"


# -- pane symbols: the instrument catalogue --------------------------------------------------


@pytest.mark.parametrize("symbol", ["LUNAUSDT", "ZZZZUSDT"])  # closed; not listed
def test_layout_pane_symbol_outside_the_catalogue_is_422_unknown_symbol(symbol: str) -> None:
    env = Env()
    env.catalogue = RECORDED
    wid = env.create()["id"]
    panes = [{"slot_index": 0, "pane_kind": "alerts"},
             {"slot_index": 1, "pane_kind": "chart", "symbol": symbol}]  # fmt: skip
    r = env.c.post(f"/workspaces/{wid}/layouts", json=_layout(panes=panes))
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
        ("panes.1.symbol", "unknown_symbol")
    ]
    assert env.repo.layouts == {}


def test_layout_write_with_no_catalogue_loaded_is_503_and_writes_nothing() -> None:
    env = Env()
    wid = env.create()["id"]
    env.catalogue = None
    r = env.c.post(f"/workspaces/{wid}/layouts", json=_layout())
    assert r.status_code == 503 and r.json()["code"] == "instrument_cache_unavailable"
    assert r.headers["Retry-After"] == "2" and env.repo.layouts == {}
    no_symbols = _layout(panes=[{"slot_index": 0, "pane_kind": "alerts"}])
    assert env.c.post(f"/workspaces/{wid}/layouts", json=no_symbols).status_code == 201


def test_layout_replace_judges_only_symbols_its_stored_layout_does_not_hold() -> None:
    env = Env()
    wid = env.create()["id"]
    env.catalogue = RECORDED
    lid = env.make_layout(wid)["id"]  # BTCUSDT, ETHUSDT, SOLUSDT
    env.catalogue = CatalogueSnapshot(  # BTCUSDT no longer listed
        {s: i for s, i in RECORDED.by_symbol.items() if s != "BTCUSDT"}, 0
    )
    url = f"/workspaces/{wid}/layouts/{lid}"
    assert env.c.put(url, json=_layout(name="Renamed")).status_code == 200
    moved = [{"slot_index": 0, "pane_kind": "chart", "symbol": "BTCUSDT"}]
    fresh = env.c.post(f"/workspaces/{wid}/layouts", json=_layout(name="New", panes=moved))
    assert fresh.status_code == 422 and fresh.json()["errors"][0]["rule"] == "unknown_symbol"


# -- SR-125: foreign-id denials --------------------------------------------------------------


def _denied(permission: str) -> float:
    labels = {"permission": permission}
    return float(REGISTRY.get_sample_value("authz_denied_total", labels) or 0.0)


@pytest.mark.parametrize(
    ("method", "path", "permission"),
    [
        ("GET", "/workspaces/{wid}", "workspaces:read"),
        ("GET", "/workspaces/{wid}/layouts", "workspaces:read"),
        ("PUT", "/workspaces/{wid}", "workspaces:write"),
        ("DELETE", "/workspaces/{wid}", "workspaces:write"),
    ],
)
def test_workspace_foreign_id_denial_counts_once_in_authz_denied_total(
    method: str, path: str, permission: str
) -> None:
    env = Env().as_user(USER_B)
    theirs = env.create()["id"]
    env.as_user(USER_A)
    before = _denied(permission)
    body = wire({"name": "X"}) if method == "PUT" else None
    r = env.c.request(method, path.format(wid=theirs), json=body)
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert _denied(permission) == before + 1
    missing = env.c.request(method, path.format(wid=MISSING), json=body)
    assert missing.json() == r.json()  # the uniform 404 (D18); a missing id is not a denial
    assert _denied(permission) == before + 1
