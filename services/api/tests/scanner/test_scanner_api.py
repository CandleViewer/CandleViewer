"""`GET /scanner` through the router (E08-T09 PR 2b, #4708; 22 `runScanner`): Gherkin 1 (the cap
over 300 symbols) and 3 (an inverted range), every 422 rule collected in one problem without
echoing a value, the order of the checks (RBAC, the query, then the scan), 401/403, 429 with
`Retry-After` and 503 with `Retry-After`."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from _scan_env import FakeRecording, FakeUniverse, entry, service, ticker
from _scan_env import universe as tickers_of
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.scanner import _UNAVAILABLE_SCAN, make_scanner_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.storage.errors import StorageTierUnavailable
from tests.scanner_presets._scanner_env import PERMS, SID, USER_A, VIEWER, Audit, FakeScannerRepo

#: A value no answer may ever echo.
CANARY = "9876543210123"


class ScanApp:
    """A router-only app over a `ScannerService` on fakes; `user` is the caller (None: no
    session), `grants` replaces its permissions and `owner` its owner flag."""

    def __init__(
        self, source: FakeUniverse | None, recording: FakeRecording | None = None, **kw: Any
    ) -> None:
        self.source, self.audit = source, Audit()
        self.recording = recording if recording is not None else FakeRecording([])
        self.svc = service(source, self.recording, **kw)
        self.user: uuid.UUID | None = USER_A
        self.grants: set[str] | None = None
        self.owner = False
        env = self

        class _Resolver:
            async def resolve(self, _request: Request) -> AuditPrincipal | None:
                if env.user is None:
                    return None
                perms = frozenset(PERMS[env.user] if env.grants is None else env.grants)
                return AuditPrincipal(
                    env.user, "u", perms, session_id=SID, ip="10.0.0.9", is_owner=env.owner
                )

        app = FastAPI()
        app.include_router(
            make_scanner_router(
                lambda: FakeScannerRepo(), _Resolver(), self.audit, scanner=self.svc
            )
        )
        self.c = TestClient(app)

    def get(self, **params: Any) -> Any:
        return self.c.get("/scanner", params=params)


def _src(n: int = 3) -> FakeUniverse:
    return FakeUniverse(
        tickers_of(ticker(f"S{i:03d}USDT", volume_24h=Decimal(i)) for i in range(n))
    )


def _errors(r: Any) -> list[tuple[str, str]]:
    assert r.status_code == 422, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    return [(e["field"], e["rule"]) for e in r.json()["errors"]]


def test_gherkin_1_three_hundred_symbols_capped_at_200_in_rank_order() -> None:
    rows = [
        ticker(f"S{i:03d}USDT", turnover_24h=Decimal(i), volume_24h=Decimal(1000 - i))
        for i in range(300)
    ]
    app = ScanApp(FakeUniverse(tickers_of(rows)))
    r = app.get(filters=json.dumps({"turnover_24h": {"min": "50"}}), limit=200)
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    body = r.json()
    assert [row["symbol"] for row in body["items"]] == [f"S{i:03d}USDT" for i in range(50, 250)]
    meta = body["meta"]
    assert (meta["count"], meta["capped"], meta["has_more"], meta["next_cursor"]) == (
        200,
        True,
        True,
        None,
    )


def test_defaults_are_volume_24h_and_100_rows() -> None:
    app = ScanApp(_src(120))
    body = app.get().json()
    assert len(body["items"]) == 100 and body["items"][0]["symbol"] == "S119USDT"
    assert body["meta"]["capped"] is True


def test_gherkin_3_an_inverted_range_is_refused_on_its_criterion() -> None:
    app = ScanApp(_src())
    for flt in ({"min": "0.01", "max": "0.001"}, {"min": "0.01", "max": "0.010"}):
        r = app.get(filters=json.dumps({"funding_rate": flt}))
        assert _errors(r) == [("filters.funding_rate", "range_inverted")]
    assert app.source is not None and app.source.refreshes == 0  # nothing evaluated


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"filters": "{not json"}, [("filters", "invalid_json")]),
        ({"filters": ""}, [("filters", "invalid_json")]),
        ({"filters": "[]"}, [("filters", "invalid_json")]),
        ({"filters": '{"funding_rate": {"min": NaN}}'}, [("filters", "invalid_json")]),
        (
            {"filters": '{"funding_rate": {"min": "1"}, "funding_rate": {"min": "2"}}'},
            [("filters", "invalid_json")],
        ),
        ({"filters": "[" * 40 + "]" * 40}, [("filters", "invalid_json")]),
        ({"filters": json.dumps({"x": "1" * 4000})}, [("filters", "string_too_long")]),
        ({"filters": json.dumps({"made_up": {"min": "1"}})}, [("filters", "unknown_criterion")]),
        ({"filters": json.dumps({"funding_rate": {}})}, [("filters.funding_rate", "range_empty")]),
        (
            {"filters": json.dumps({"funding_rate": {"min": "1e3"}})},
            [("filters.funding_rate", "invalid_decimal")],
        ),
        (
            {"filters": json.dumps({"regime": {"classes": []}})},
            [("filters.regime", "classes_empty")],
        ),
        (
            {"filters": json.dumps({"regime": {"classes": ["sideways"]}})},
            [("filters.regime", "unknown_regime_class")],
        ),
        (
            {"filters": json.dumps({"regime": {"classes": ["calm"]}})},
            [("filters.regime", "criterion_unavailable")],
        ),
        (
            {"filters": json.dumps({"tape_speed_zscore": {"min": "2"}})},
            [("filters.tape_speed_zscore", "criterion_unavailable")],
        ),
        ({"sort": "cvd"}, [("sort", "criterion_unavailable")]),
        ({"sort": "oi_change_pct_24h"}, [("sort", "criterion_unavailable")]),
        ({"sort": "loudest"}, [("sort", "literal_error")]),
        ({"limit": "0"}, [("limit", "greater_than_equal")]),
        ({"limit": "201"}, [("limit", "less_than_equal")]),
        ({"limit": "ten"}, [("limit", "int_parsing")]),
    ],
)
def test_each_422_rule(params: dict[str, str], expected: list[tuple[str, str]]) -> None:
    app = ScanApp(_src())
    assert _errors(app.get(**params)) == expected
    assert app.source is not None and app.source.refreshes == 0


def test_a_repeated_key_is_multiple_values_never_the_last_one_wins() -> None:
    app = ScanApp(_src())
    for name, a, b in (
        ("limit", "5", "6"),
        ("sort", "volume_24h", "funding_rate"),
        ("filters", "{}", "{}"),
    ):
        r = app.c.get(f"/scanner?{name}={a}&{name}={b}")
        assert _errors(r) == [(name, "multiple_values")]


def test_every_defect_is_collected_in_one_problem() -> None:
    app = ScanApp(_src())
    flt = {"funding_rate": {"min": "2", "max": "1"}, "spread_bps": {}, "nope": {}}
    r = app.c.get("/scanner", params={"filters": json.dumps(flt), "sort": "cvd", "limit": "0"})
    assert sorted(_errors(r)) == sorted(
        [
            ("filters.funding_rate", "range_inverted"),
            ("filters.spread_bps", "range_empty"),
            ("filters", "unknown_criterion"),
            ("sort", "criterion_unavailable"),
            ("limit", "greater_than_equal"),
        ]
    )


def test_an_undeclared_parameter_is_refused_before_the_values_are_read() -> None:
    app = ScanApp(_src())
    r = app.c.get("/scanner", params={"filters": "{bad", "user_id": str(USER_A)})
    assert _errors(r) == [("query.user_id", "undeclared_parameter")]


def test_no_problem_echoes_a_submitted_value() -> None:
    app = ScanApp(_src())
    sent = [
        {"filters": json.dumps({"funding_rate": {"min": CANARY, "max": "1"}})},
        {"filters": json.dumps({CANARY: {"min": "1"}})},
        {"filters": json.dumps({"regime": {"classes": [f"c{CANARY}"]}})},
        {"filters": "{" + CANARY},
        {"sort": CANARY},
        {"limit": CANARY + "0"},
    ]
    for params in sent:
        r = app.get(**params)
        assert r.status_code == 422 and CANARY not in r.text, r.text


def test_a_valid_filter_scans_and_the_rows_match_it() -> None:
    rows = [ticker("AAAUSDT", funding_rate=Decimal("0.001")), ticker("BBBUSDT")]
    app = ScanApp(FakeUniverse(tickers_of(rows)), FakeRecording([entry("AAAUSDT")]))
    r = app.get(filters=json.dumps({"funding_rate": {"min": "0.0005"}}), sort="funding_rate")
    assert [(i["symbol"], i["coverage"]) for i in r.json()["items"]] == [("AAAUSDT", "recorded")]


def test_unauthenticated_is_401_and_without_marketdata_read_403() -> None:
    app = ScanApp(_src())
    app.user = None
    assert app.get(filters="{bad").status_code == 401
    app.user, app.grants = VIEWER, {"workspaces:read"}
    r = app.get(filters="{bad")
    assert r.status_code == 403 and r.json()["required_permissions"] == ["marketdata:read"]
    assert [c["action"] for c in app.audit.calls] == ["rbac.denied"]
    assert app.source is not None and app.source.refreshes == 0


@pytest.mark.parametrize(("user", "owner"), [(USER_A, True), (USER_A, False), (VIEWER, False)])
def test_every_role_holding_marketdata_read_scans(user: uuid.UUID, owner: bool) -> None:
    app = ScanApp(_src())
    app.user, app.owner = user, owner
    assert app.get().status_code == 200


def test_the_owner_sees_hidden_recording_causes_and_others_do_not() -> None:
    held = FakeRecording([entry("S000USDT", reasons=("position_open",))])
    app = ScanApp(_src(1), held)
    app.owner = True
    assert app.get().json()["items"][0]["coverage"] == "recorded"
    app.owner = False
    assert app.get().json()["items"][0]["coverage"] == "live_only"


def test_past_the_cold_bound_is_429_with_retry_after() -> None:
    app = ScanApp(_src(), max_cold=0)
    r = app.get()
    assert (r.status_code, r.headers["retry-after"], r.json()["code"]) == (429, "1", "rate_limited")


def test_no_ticker_snapshot_or_no_recorded_set_is_503_with_retry_after() -> None:
    for app in (
        ScanApp(None),
        ScanApp(FakeUniverse(None)),
        ScanApp(_src(), FakeRecording([], fail=OSError("down"))),
    ):
        r = app.get()
        assert (r.status_code, r.headers["retry-after"], r.json()["code"]) == (
            503,
            "5",
            "store_unavailable",
        )


def test_a_storage_outage_past_the_recorded_set_answers_the_scan_503_not_the_presets_one() -> None:
    def listed() -> frozenset[str]:
        raise StorageTierUnavailable("catalogue down")

    r = ScanApp(_src(), listed=listed).get()
    assert (r.status_code, r.headers["retry-after"], r.json()["code"]) == (
        503,
        "5",
        "store_unavailable",
    )
    assert r.json()["detail"] == _UNAVAILABLE_SCAN


def test_no_scanner_wired_is_503_after_rbac_and_validation() -> None:
    application = FastAPI()
    audit = Audit()

    class _Resolver:
        async def resolve(self, _request: Request) -> AuditPrincipal | None:
            return AuditPrincipal(
                USER_A, "u", frozenset(PERMS[USER_A]), session_id=SID, ip="10.0.0.9"
            )

    application.include_router(make_scanner_router(lambda: None, _Resolver(), audit))
    client = TestClient(application)
    assert client.get("/scanner", params={"limit": "0"}).status_code == 422
    assert client.get("/scanner").status_code == 503
