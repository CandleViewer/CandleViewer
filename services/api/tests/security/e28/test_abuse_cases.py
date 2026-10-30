"""E28-X03 (#976): the abuse cases AC-01 to AC-10 of the E28 threat model (section 7), with
SR-E28-21, through the routes `create_app()` serves in the E28 world. Each case asserts the refusal
and what it records under the request's own id (`X-Correlation-Id`, #3990), and, where nothing
may be written, that no store changed. Where the threat model and the ticket's wording differ the
threat model wins; each delta is recorded in `docs/security/e28/abuse-suite-report.md`, and the
submit halves (E34-S02 #1110, E34-S03 #1111) wait on `createTradeGroup` being mounted.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.accounts.profiles import SymbolEntries, SymbolScope
from candleviewer.domain.primitives import AccountId
from tests.contract.rbac.rbac_harness import ABSENT, FOREIGN, GRANTED, bearer
from tests.contract.test_account_profile_write_cells import _step_up
from tests.contract.test_account_profile_writes_provider import _ALT, _RISK, ALT
from tests.security.e28._world import GROUP, LIVE, READ_LOGS, E28World, request_id, state
from tests.unit.api.test_trade_group_definition_create import A, L, payload
from tests.unit.api.test_trade_group_definition_update import CORE3
from tests.unit.api.test_trade_group_preview_route import body
from tests.unit.oms.submit_rig import instrument, profile

M, PREVIEW = "manager_with_grant", "/trade-groups/preview"
PROFILES, PREVIEWED = f"/exchange-accounts/{GRANTED}/profiles", "trade_group.previewed"
REFUSED, SAVE_REFUSED = "trade_group.override_refused", "profile.save_refused"
_TAG = {"if-match": f'W/"{ALT}:2"'}


def call(
    world: E28World, name: str, method: str, path: str, actor: str = "owner", **kw: Any
) -> tuple[Any, list[tuple[str, Any]]]:
    """One request, stamped with its own id: the answer and its records, `(action, reason)`."""
    rid = request_id(f"abuse|{name}")
    headers = {**bearer(actor), "X-Correlation-Id": rid, **kw.pop("headers", {})}
    resp = world.writes.world.client.request(method, path, headers=headers, **kw)
    return resp, [(r["action"], r.get("reason")) for r in world.by_request.get(rid, [])]


@pytest.fixture
def unchanged(world: E28World) -> Iterator[E28World]:
    """The case changes no store: every one walked before and after (the read logs aside)."""
    before = state(world.stores(), skip=READ_LOGS)
    yield world
    assert state(world.stores(), skip=READ_LOGS) == before, "a refused call changed a store"


_NO_SL = {"require_native_stop": False}
_RAW = json.dumps(_RISK)[:-1].encode() + b', "require_native_stop": false}'  # a duplicate, last


@pytest.mark.parametrize(
    ("method", "path", "sent"),
    [
        ("POST", PROFILES, {"json": _RISK | _NO_SL}),
        ("PUT", f"{PROFILES}/{ALT}", {"json": _ALT | _NO_SL, "headers": _TAG}),
        ("POST", PROFILES, {"content": _RAW, "headers": {"content-type": "application/json"}}),
    ],
    ids=["create", "update", "raw-payload"],
)
def test_ac01_native_sl_off_is_refused_on_every_path_and_audited(
    unchanged: E28World, method: str, path: str, sent: dict[str, Any]
) -> None:
    """SR-E28-08, SR-052: `require_native_stop = false` by create, update and a hand-made payload
    (the key repeated, false last) is 422 `native_stop_mandatory`, recorded, nothing written."""
    resp, records = call(unchanged, f"ac01|{method}|{len(str(sent))}", method, path, **sent)
    rules = [e["rule"] for e in resp.json()["errors"]]
    assert (resp.status_code, rules) == (422, ["native_stop_mandatory"])
    assert records == [(SAVE_REFUSED, "native_stop_mandatory")]


def test_ac02_a_symbol_off_the_allow_list_is_never_planned_and_is_recorded(
    unchanged: E28World,
) -> None:
    """SR-E28-06, PF-T07: as M, a preview of ETHUSDT (listed) for account A, whose profile allows
    BTCUSDT alone: the leg is not planned (`would_submit: false`, `symbol_not_allowed`) and the
    preview is recorded. The preview sends nothing (SR-E28-22); a submit's 403 is E34-S02's."""
    resp, records = call(unchanged, "ac02", "POST", PREVIEW, M, json=body(GRANTED) | {
        "symbol": "ETHUSDT"})  # fmt: skip
    (leg,) = resp.json()["legs"]
    assert (resp.status_code, leg["would_submit"], leg["rejection"]["code"]) == (
        200, False, "symbol_not_allowed",
    )  # fmt: skip
    assert records == [(PREVIEWED, None)]


def test_ac03_an_oversized_quantity_hint_is_refused_never_clamped(unchanged: E28World) -> None:
    """D6, SR-052: a size past the day's loss cap is `403 risk_limit_breached`, each offending
    leg's `trade_group.override_refused` written ahead of the preview's record."""
    big = {"sizing": {"mode": "fixed_qty", "qty": "0.2"}}
    resp, records = call(unchanged, "ac03", "POST", PREVIEW, M, json=body((GRANTED, big)))
    assert (resp.status_code, resp.json()["code"]) == (403, "risk_limit_breached")
    assert records == [(REFUSED, "risk_limit_breached"), (PREVIEWED, "risk_limit_breached")]


#: An alternate of A's wider on one cap, and a leg override past the bound profile's value of it
#: but inside the alternate's: the bound profile stays the ceiling (SR-E28-03).
_WIDER: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "max_position_notional": ({"max_position_notional": "40000", "max_daily_loss": "100000"},
                              {"sizing": {"mode": "fixed_qty", "qty": "0.4"}}),
    "max_daily_loss": ({"max_daily_loss": "100000"},
                       {"sizing": {"mode": "fixed_qty", "qty": "0.2"}}),
    "max_leverage_cap": ({"max_leverage_cap": "20"}, {"leverage": "15"}),
}  # fmt: skip


@pytest.mark.parametrize("cap", list(_WIDER))
def test_ac04_an_alternate_widening_a_cap_is_refused_and_audited(
    unchanged: E28World, cap: str
) -> None:
    alternate, override = uuid.UUID(int=0xA170 + list(_WIDER).index(cap)), _WIDER[cap]
    unchanged.preview.alternates[alternate] = profile(
        AccountId(GRANTED), profile_id=str(alternate), is_default=False, **override[0]
    )
    try:
        sent = body((GRANTED, {"profile_id": str(alternate), **override[1]}))
        resp, records = call(unchanged, f"ac04|{cap}", "POST", PREVIEW, M, json=sent)
    finally:
        del unchanged.preview.alternates[alternate]
    assert (resp.status_code, resp.json()["code"]) == (403, "risk_limit_breached")
    assert records == [(REFUSED, "risk_limit_breached"), (PREVIEWED, "risk_limit_breached")]
    assert resp.json()["errors"][0]["rule"] in _WIDER


@pytest.mark.parametrize("wider", [{"allowed_symbols": ["BTCUSDT", "ETHUSDT"]},
                                   {"all_symbols": True, "allowed_symbols": []}])  # fmt: skip
def test_ac04_an_alternate_widening_the_symbol_list_plans_nothing_off_the_bound_list(
    unchanged: E28World, wider: dict[str, Any]
) -> None:
    """The allow-list and `all_symbols`: the bound profile's list still decides the leg."""
    alternate = uuid.UUID(int=0xA17F)
    made = profile(AccountId(GRANTED), profile_id=str(alternate), is_default=False, **wider)
    unchanged.preview.alternates[alternate] = made
    try:
        sent = body((GRANTED, {"profile_id": str(alternate)})) | {"symbol": "ETHUSDT"}
        resp, records = call(unchanged, f"ac04|{sorted(wider)}", "POST", PREVIEW, M, json=sent)
    finally:
        del unchanged.preview.alternates[alternate]
    (leg,) = resp.json()["legs"]
    assert (leg["would_submit"], leg["rejection"]["code"]) == (False, "symbol_not_allowed")
    assert records == [(PREVIEWED, None)]


def test_ac04_native_sl_cannot_be_overridden_at_all(unchanged: E28World) -> None:
    """`require_native_sl` is no override member (22 `Overrides`): 422, recorded."""
    sent = body((GRANTED, {"require_native_sl": False}))
    resp, records = call(unchanged, "ac04|native", "POST", PREVIEW, M, json=sent)
    assert (resp.status_code, resp.json()["errors"][0]["rule"]) == (422, "extra_forbidden")
    assert records == [(PREVIEWED, "extra_forbidden")]


def test_ac05_a_preview_mixing_demo_and_live_is_refused_and_recorded(unchanged: E28World) -> None:
    """SR-E28-16, C-2.11: a leg in another environment is 400 `environment_mismatch`."""
    resp, records = call(unchanged, "ac05|preview", "POST", PREVIEW, json=body(GRANTED, LIVE))
    assert [(e["field"], e["rule"]) for e in resp.json()["errors"]] == [
        ("legs[1].exchange_account_id", "environment_mismatch")]  # fmt: skip
    assert (resp.status_code, records) == (400, [(PREVIEWED, "environment_mismatch")])


_DEFINITION_WRITES = [
    ("POST", "/trade-group-definitions"),
    ("PUT", f"/trade-group-definitions/{CORE3}"),
]


@pytest.mark.parametrize(("method", "path"), _DEFINITION_WRITES)
def test_ac05_a_definition_made_or_edited_to_span_environments_is_refused(
    unchanged: E28World, method: str, path: str
) -> None:
    """The definitions are the one edit-after-creation path: a mixed membership on create and on
    a replace is 400 `environment_mismatch` before any challenge or write. The stored trigger is
    `test_tg_frozen_after_draft_pg`'s. † Known gap, #5120: the refusal writes no audit record
    yet (C-2.11's class should). This pins today's absence; #5120 flips it to the record."""
    sent = payload(A, L, name="Core3")
    resp, records = call(unchanged, f"ac05|{method}", method, path, json=sent)
    rules = [e["rule"] for e in resp.json()["errors"]]
    assert (resp.status_code, rules, records) == (400, ["environment_mismatch"], [])


def test_ac06_an_ungranted_and_an_absent_account_answer_the_preview_alike(
    unchanged: E28World,
) -> None:
    """SR-E28-21, SR-E29-13, PF-I01: one `account_scope_denied` shape, byte for byte, whether the
    account exists or not, with no figure of it; each refusal recorded `rbac.denied` first."""
    got = [
        call(unchanged, f"ac06|{a}", "POST", PREVIEW, M, json=body(a)) for a in (FOREIGN, ABSENT)
    ]
    assert got[0][0].content == got[1][0].content
    assert (got[0][0].status_code, got[0][0].json()["code"]) == (403, "account_scope_denied")
    for _, records in got:
        assert records == [("rbac.denied", "account_not_granted:orders:write:granted_accounts"),
                           (PREVIEWED, "account_scope_denied")]  # fmt: skip


def test_ac07_a_profile_write_without_step_up_is_challenged_and_recorded(
    unchanged: E28World,
) -> None:
    """SR-E28-02, SR-025: the Owner with no `risk_caps` window is challenged by the production
    step-up service (its B16 chart records the challenge), and nothing is written."""
    world, service = unchanged, _step_up("owner", False)
    auth = world.app.state.app_context.auth
    kept, auth._step_up = auth._step_up, service
    try:
        with world.writes.world.client as client:  # one loop, so B16's chart outlives the request
            assert client.portal is not None
            resp, records = call(world, "ac07", "POST", PROFILES, json=_RISK)
            client.portal.call(service.stop)
    finally:
        auth._step_up = kept
    assert (resp.status_code, resp.json()["code"]) == (403, "step_up_required")
    assert [a for a, _ in records] == ["auth.step_up_required"]


_SUFFIX = st.from_regex(r"[A-Z0-9]{4,12}", fullmatch=True)
#: A USDC perpetual, an inverse contract, a USDT one no longer trading, a USDC-settled one.
_NOT_PERP = st.sampled_from(
    [("USDC", "USDC", "trading"), ("USD", "BTC", "trading"), ("USDT", "USDT", "delivering"),
     ("USDT", "USDC", "trading")]
)  # fmt: skip


@settings(max_examples=200, deadline=None, derandomize=True)
@given(suffix=_SUFFIX, prefix=st.from_regex(r"[A-Z]{1,6}", fullmatch=True),
       kind=_NOT_PERP)  # fmt: skip
def test_ac08_a_crafted_suffix_pattern_never_admits_what_is_not_a_listed_usdt_perp(
    suffix: str, prefix: str, kind: tuple[str, str, str]
) -> None:
    """SR-E28-06, PF-T07, seeded: an anchored `*<suffix>` admits no symbol that is not a trading
    linear USDT perpetual (a USDC, inverse, settling or USDC-settled contract ending in it), nor
    the bare suffix, nor a symbol it is only a substring of, through the one matcher both the order
    path and a save use."""
    quote, settle, status = kind
    scope = SymbolScope(False, SymbolEntries.of([f"*{suffix}"]), SymbolEntries.of([]))
    crafted = instrument(
        symbol=prefix + suffix, quote_coin=quote, settle_coin=settle, status=status
    )
    assert not scope.admits(crafted)
    listed = {"quote_coin": "USDT", "settle_coin": "USDT", "status": "trading"}
    assert not scope.admits(instrument(symbol=suffix, **listed))  # never the whole symbol
    inside = f"{suffix}{prefix}"  # the suffix inside a symbol that does not end with it
    assert inside.endswith(suffix) or not scope.admits(instrument(symbol=inside, **listed))


@pytest.mark.parametrize("pattern", ["*", "*USD", "*BTC-26DEC", "BTC*"])
def test_ac08_a_bare_short_or_malformed_pattern_is_refused_at_save(
    unchanged: E28World, pattern: str
) -> None:
    sent = _RISK | {"allowed_symbols": [pattern]}
    resp, _ = call(unchanged, f"ac08|{pattern}", "POST", PROFILES, json=sent)
    assert resp.status_code == 422
    assert {e["field"].split("[")[0] for e in resp.json()["errors"]} == {"allowed_symbols"}


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_ac09_an_idempotency_key_reused_with_another_body_is_409(
    world: E28World, method: str
) -> None:
    """SR-E28-17: the key's first write is kept; another request under it is `409
    idempotency_key_reuse` and writes nothing more."""
    key = str(uuid.uuid4())
    first = {"POST": (PROFILES, _RISK), "PUT": (f"{PROFILES}/{ALT}", _ALT),
             "DELETE": (f"{PROFILES}/{ALT}", None)}[method]  # fmt: skip
    again = {"POST": (PROFILES, _RISK | {"name": "Other"}),
             "PUT": (f"{PROFILES}/{ALT}", _ALT | {"name": "Other"}),
             "DELETE": (f"{PROFILES}/{uuid.UUID(int=1)}", None)}[method]  # fmt: skip
    headers = {"idempotency-key": key, **_TAG}
    done, _ = call(world, f"ac09|{method}|1", method, first[0], json=first[1], headers=headers)
    assert done.status_code < 300
    before = state(world.stores(), skip=READ_LOGS)
    resp, records = call(
        world, f"ac09|{method}|2", method, again[0], json=again[1], headers=headers
    )
    assert (resp.status_code, resp.json()["code"], records) == (409, "idempotency_key_reuse", [])
    assert state(world.stores(), skip=READ_LOGS) == before


def test_ac10_a_client_profile_snapshot_is_refused_never_read(unchanged: E28World) -> None:
    """PF-T06: `additionalProperties: false` (22): a client `profile_snapshot` is a 422,
    recorded; the server's own snapshot is the only one there is."""
    sent = body(GRANTED) | {"profile_snapshot": {"max_leverage_cap": "100"}}
    resp, records = call(unchanged, "ac10", "POST", PREVIEW, M, json=sent)
    assert (resp.status_code, resp.json()["errors"][0]["rule"]) == (422, "extra_forbidden")
    assert records == [(PREVIEWED, "extra_forbidden")]


def test_sr_e28_21_a_group_with_a_leg_outside_the_grants_is_never_listed(
    unchanged: E28World,
) -> None:
    """AC-29: M's list holds its granted group alone; the mixed one is as absent as the foreign."""
    resp, records = call(unchanged, "sr21", "GET", "/trade-groups", M)
    listed = {item["id"] for item in resp.json()["items"]}
    assert (resp.status_code, listed, records) == (200, {str(GROUP["granted"])}, [])
    assert str(FOREIGN) not in resp.text


def test_ac11_another_accounts_profile_id_answers_as_a_missing_one(unchanged: E28World) -> None:
    """AC-11's second half, PF-T03: an override naming a profile of another account is the 404
    an unknown profile id gets, byte for byte, each recorded alike."""
    other = uuid.UUID(int=0x0B0F)
    sent = [body((GRANTED, {"profile_id": str(p)})) for p in (other, uuid.UUID(int=0xAB5E))]
    unchanged.preview.alternates[other] = profile(
        AccountId(FOREIGN), profile_id=str(other), is_default=False
    )
    try:
        got = [call(unchanged, f"ac11|{i}", "POST", PREVIEW, M, json=s) for i, s in enumerate(sent)]
    finally:
        del unchanged.preview.alternates[other]
    assert got[0][0].status_code == 404 and got[0][0].content == got[1][0].content
    assert got[0][1] == got[1][1] == [(PREVIEWED, "not_found")]


def test_ac15_one_account_repeated_in_the_legs_is_422_before_any_read(
    unchanged: E28World,
) -> None:
    """AC-15's preview half, PF-T17: a repeated account is refused whole, recorded."""
    resp, records = call(unchanged, "ac15", "POST", PREVIEW, M, json=body(*[GRANTED] * 25))
    assert resp.status_code == 422
    assert len(records) == 1 and records[0][0] == PREVIEWED
