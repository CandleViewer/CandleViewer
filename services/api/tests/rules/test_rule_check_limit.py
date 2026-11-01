"""#4834 (E35 authoring limits, G-2): validate and compile share one token bucket per user.

A bucket of `rules_check_rate_per_user_per_second` tokens a second (10) with a burst of twice the
rate (20), one per user across sessions, taken after `_authorize` and before the body is read.
Past it the answer is `429 rate_limited` with a whole-second `Retry-After` (at least 1) and
`retry_after_seconds`; no audit record is written, and the call is counted under
`rule_authoring_rate_limited_total{route}`. Clocks are fake; nothing sleeps.
"""

from __future__ import annotations

import re
import time
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from pydantic import ValidationError

from candleviewer.api.preview_limiter import PreviewLimiter
from candleviewer.api.rules import CHECK_BURST_FACTOR, CHECK_ROUTES, make_rules_router
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.rules.compiler import to_form_model
from candleviewer.rules.ir import Rule
from candleviewer.rules.manager import REFUSED_CAPS
from candleviewer.rules.service import RulesService
from candleviewer.rules.vocabulary import default_registry
from candleviewer.settings import RULES_CHECK_RATE_PER_USER_PER_SECOND, Settings
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.contract._admin_support import validate_example
from tests.rules.test_rules_routes import _ir
from tests.rules.test_scope_crud import C as UNGRANTED
from tests.rules.test_scope_crud import _Src
from tests.rules.test_validator_endpoints import RULE_ID, _jsonable, _rule

RATE = RULES_CHECK_RATE_PER_USER_PER_SECOND
BURST = RATE * CHECK_BURST_FACTOR
ONE, TWO = UUID(int=1), UUID(int=2)
REG = default_registry()
MODEL = _jsonable(to_form_model(_rule()))  # the model compile is sent
_ENV = "CV_RULES_CHECK_RATE_PER_USER_PER_SECOND"


class _Who:
    """A principal; `user_id` is absent for one that carries no identity."""

    def __init__(self, perms: str, user: UUID | None, session: str) -> None:
        self._perms, self.session_id = frozenset(perms.split(",")), session
        if user is not None:
            self.user_id = user

    def has(self, permission: str) -> bool:
        return permission in self._perms


class _Resolver:
    """Who calls comes from the headers: `x-user` (a UUID, `none` or absent: nobody, `401`),
    `x-perms`, `x-session`."""

    def resolve(self, request: Request) -> _Who | None:
        user, h = request.headers.get("x-user"), request.headers
        if user is None:
            return None
        who = None if user == "none" else UUID(user)
        return _Who(h.get("x-perms", "rules:read"), who, h.get("x-session", "s"))


class _Rig:
    """The checks behind a limiter on a fake clock: the 429s counted, the scope records written."""

    def __init__(self) -> None:
        self.limited: list[str] = []
        self.records: list[str] = []
        self.limiter = PreviewLimiter(RATE, burst=BURST, clock=lambda: 1000.0)  # time stands still
        service = RulesService()

        async def sink(event: str, _data: dict[str, str]) -> None:
            self.records.append(event)

        service.wire_scope(_Src(), "demo", sink)
        router = make_rules_router(
            lambda: REG,
            principal_resolver=_Resolver(),
            check_limiter=self.limiter,
            on_rate_limited=self.limited.append,
            scope_resolver=service.scope_resolver,
            scope_refresh=service.refresh_scope,
        )
        app = FastAPI()
        app.include_router(router)
        self.c = TestClient(app)

    def call(
        self,
        route: str,
        user: UUID | str | None = ONE,
        perms: str = "rules:read",
        session: str = "s",
    ) -> Any:
        """A validate or a compile as `user`, who is nobody when `None`."""
        sent = {"x-perms": perms, "x-session": session}
        sent |= {} if user is None else {"x-user": str(user)}
        if route == "compile":
            body = {"editor": "form", "model": MODEL}
            return self.c.post(f"/rules/{RULE_ID}/compile", json=body, headers=sent)
        return self.c.post("/rules/validate", json={"ir": _ir()}, headers=sent)

    def exhaust(self, user: UUID | str = ONE) -> None:
        """The burst, none refused by the limit (a principal with no identity is let through it and
        then refused by the scope check, so only the limit's answer is told apart)."""
        assert 429 not in {self.call("validate", user).status_code for _ in range(BURST)}


def test_validate_past_the_burst_is_429_with_a_whole_second_retry_after() -> None:
    rig = _Rig()
    rig.exhaust()
    r = rig.call("validate")
    assert r.status_code == 429 and r.headers["content-type"] == "application/problem+json"
    wait = int(r.headers["Retry-After"])
    assert wait >= 1 and r.headers["Retry-After"] == str(wait)
    assert r.json() == {
        "type": "https://candleviewer.local/errors/rate_limited",
        "title": ERROR_META[ErrorCode.RATE_LIMITED].title,
        "status": 429,
        "code": "rate_limited",
        "detail": "Too many rule checks; retry after the delay given.",
        "retry_after_seconds": wait,
    }
    validate_example("/components/schemas/Problem", r.json())
    assert rig.limited == ["validate"]


def test_validate_and_compile_draw_from_one_bucket_per_user() -> None:
    rig = _Rig()
    for i in range(BURST):
        assert rig.call(("compile", "validate")[i % 2]).status_code == 200
    assert (rig.call("validate").status_code, rig.call("compile").status_code) == (429, 429)
    assert rig.limited == ["validate", "compile"]
    assert rig.call("validate", TWO).status_code == 200  # another user's bucket is its own


def test_a_throttled_call_reads_no_body_and_compiles_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _Rig()
    rig.exhaust()

    def reached(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a throttled call went on to read or compile")

    monkeypatch.setattr("candleviewer.api.rules.read_object", reached)
    monkeypatch.setattr(Rule, "model_validate", classmethod(reached))
    assert [rig.call(route).status_code for route in ("validate", "compile")] == [429, 429]


def test_a_throttled_call_is_counted_by_route_and_writes_no_record() -> None:
    """An ungranted account in the rule is refused and recorded when the call is let through: a
    throttled call never reaches the scope check, so it writes none."""
    ungranted = {"level": "account", "account_ids": [str(UNGRANTED)]}
    rig = _Rig()
    body = {"ir": _ir(scope=ungranted)}
    sent = {"x-user": str(ONE)}
    assert rig.c.post("/rules/validate", json=body, headers=sent).status_code == 403
    assert rig.records == ["rule_scope_denied"]
    rig = _Rig()
    rig.exhaust()
    assert rig.c.post("/rules/validate", json=body, headers=sent).status_code == 429
    assert rig.call("compile").status_code == 429
    assert rig.limited == ["validate", "compile"] and rig.records == []


def test_a_403_and_a_401_take_no_token_and_the_gate_answers_first() -> None:
    rig = _Rig()
    for _ in range(3 * BURST):
        assert rig.call("validate", perms="orders:read").status_code == 403
        assert rig.call("compile", perms="orders:read").status_code == 403
        assert rig.call("validate", None).status_code == 401
    rig.exhaust()  # the full burst is still there
    assert rig.limited == []


def test_two_users_have_two_buckets_and_two_sessions_of_one_user_share_one() -> None:
    rig = _Rig()
    for i in range(BURST):  # three sessions of the one user
        assert rig.call("validate", session=f"s{i % 3}").status_code == 200
    assert rig.call("validate", session="s4").status_code == 429
    assert rig.call("validate", TWO).status_code == 200


def test_a_principal_with_no_user_id_shares_one_fallback_bucket() -> None:
    rig = _Rig()
    rig.exhaust("none")
    assert [
        rig.call(r, "none", session="another").status_code for r in ("validate", "compile")
    ] == [
        429,
        429,
    ]
    assert rig.call("validate", ONE).status_code == 200  # a user with an id has a bucket of its own


def test_the_routes_outside_the_limit_are_untouched() -> None:
    rig = _Rig()
    rig.exhaust()
    for path in ("/rules/vocabulary", "/rules/accounts", "/schemas/rule-ir.json"):
        assert rig.c.get(path, headers={"x-user": str(ONE)}).status_code == 200


def test_the_default_is_10_a_second_with_a_burst_of_20_and_startup_refuses_outside_1_to_100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    assert (RATE, BURST) == (10, 20)
    assert Settings().rules_check_rate_per_user_per_second == RATE
    for value in ("1", "100"):
        monkeypatch.setenv(_ENV, value)
        assert Settings().rules_check_rate_per_user_per_second == int(value)
    for value in ("0", "101"):
        monkeypatch.setenv(_ENV, value)
        with pytest.raises(ValidationError, match="rules_check_rate_per_user_per_second"):
            Settings()


def _series(text: str, name: str, label: str) -> dict[str, str]:
    """The samples of `rule_authoring_<name>_total` by `label`, the one label besides `env`."""
    lines = [ln for ln in text.splitlines() if ln.startswith(f"rule_authoring_{name}_total{{")]
    assert all(set(re.findall(r"(\w+)=", ln.split("}")[0])) == {label, "env"} for ln in lines)
    return {ln.split(f'{label}="')[1].split('"')[0]: ln.rsplit(" ", 1)[1] for ln in lines}


def test_create_app_wires_the_limit_from_the_setting_and_the_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candleviewer import app as app_module

    seen: dict[str, Any] = {}

    def spy(name: str, make: Any) -> Any:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            seen[name] = kwargs
            return make(*args, **kwargs)

        return wrapped

    monkeypatch.setattr(app_module, "make_rules_router", spy("checks", make_rules_router))
    monkeypatch.setattr(app_module, "make_rules_crud_router", spy("saves", make_rules_crud_router))
    app = app_module.create_app(Settings(rules_check_rate_per_user_per_second=1))
    limiter = seen["checks"]["check_limiter"]
    assert limiter._clock is time.monotonic  # the injected clock is the monotonic one
    limiter._clock = lambda: 100.0  # frozen, so no refill can land between the calls
    assert [limiter.try_take(ONE) for _ in range(3)] == [None, None, 1]  # a rate of 1, a burst of 2
    for route in CHECK_ROUTES:
        seen["checks"]["on_rate_limited"](route)
    for router in ("checks", "saves"):  # each router counts a refusal at a bound
        seen[router]["on_cap_refused"]("condition_nodes")
    text = generate_latest(app.state.metrics_facade.registry).decode()
    assert _series(text, "rate_limited", "route") == {"validate": "1.0", "compile": "1.0"}
    capped = _series(text, "cap_refused", "cap")
    assert capped == dict.fromkeys(REFUSED_CAPS, "0.0") | {"condition_nodes": "2.0"}
    for name, label, closed in (
        ("cap_refused", "cap", REFUSED_CAPS),
        ("rate_limited", "route", CHECK_ROUTES),
    ):  # each series is catalogued live, bounded by its closed set, labelled by it alone
        (spec,) = [s for s in CATALOGUE if s.name == f"rule_authoring_{name}_total"]
        assert (spec.kind, spec.labels, spec.max_series) == ("counter", (label,), len(closed))
        assert (spec.status, spec.owner_epic) == ("live", "E35")
