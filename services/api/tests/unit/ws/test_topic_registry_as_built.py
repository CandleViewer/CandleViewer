"""#2823: what the server does for the rows of `23-ws-protocol.md` §5, §6 and §12.1 that the doc
records as built (rows a-g of #2823). The contract test beside the conformance suite,
`tests/contract/ws/test_ws_topic_registry_as_built.py`, pins the doc against the registry.

a. the keys `ctl` takes, and which re-snapshot (§5.4); b. one default throttle per family (§6.1);
c. no topic takes `params` (§6.1); d. an account-scoped private topic needs `exchange_account_ids`
(§6.2); e. `encoding_unsupported` means "no binary form" and nothing else (§5.1); f. one option
map per family (§6.1); g. the subscribe-side metrics (§6.2).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

import pytest
from prometheus_client import REGISTRY

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws.permissions import ConnectionAuthz, handle_unsub
from candleviewer.ws.topics import CTL_KEYS, FAMILIES
from tests.unit.ws.test_subscriptions import OWNER_ID, A, _ctl, _mgr, _services, _sub
from tests.unit.ws.test_subscriptions_socket import JSON, _recv, _World

ACC: Final = str(A)


def _owner() -> ConnectionAuthz:
    owner = PrincipalSnapshot(OWNER_ID, frozenset({"owner"}), frozenset(Permission))
    return ConnectionAuthz(owner, _services())


def _manager() -> ConnectionAuthz:
    """Holds every permission and one account, so a refusal can only be the account rule."""
    return ConnectionAuthz(_mgr(A, perms=frozenset(Permission)), _services())


def _refusal(result: dict[str, Any]) -> tuple[Any, ...]:
    """(ok, code, field) of a refused `sub` result or of an `err` frame."""
    body = result.get("error", result.get("p", {}))
    return (result.get("ok", False), body["code"], body.get("field"))


# One sample topic per public family, and for each `ctl` key a valid value and the families whose
# options carry it (`None`: all), as §5.4 records; the keys whose change re-snapshots.
_TOPICS: Final = (
    "book.BTCUSDT.50 trades.BTCUSDT bars.BTCUSDT.time.1 footprint.BTCUSDT.time.5 heatmap.BTCUSDT "
    "profile.BTCUSDT.volume metrics.BTCUSDT ticker.BTCUSDT liquidations.BTCUSDT"
).split()
_CTL: Final[dict[str, tuple[Any, set[str] | None]]] = {
    "throttle_ms": (500, None),
    "coalesce": (False, None),
    "paused": (True, None),
    "min_size": ("1", {"trades"}),
    "price_grouping": (2, {"footprint", "heatmap", "profile"}),
    "depth": (200, {"heatmap"}),
    "time_bucket_ms": (1000, {"heatmap"}),
    "metrics": (["cvd"], {"metrics"}),
}
_RESNAPSHOT: Final = {"price_grouping", "depth", "time_bucket_ms", "metrics"}
_OTHER_KEYS: Final = dict(bar_type="range", param="10", encoding="binary", from_seq=1, from_ts_ms=1)


@pytest.mark.parametrize("key", sorted(CTL_KEYS))  # a key missing from `_CTL` fails here
def test_a_ctl_takes_a_key_only_where_the_topic_has_that_option(key: str) -> None:
    value, families = _CTL[key]
    for ch in _TOPICS:
        conn = _owner()
        assert _sub(conn, ch)[0]["ok"], ch
        sub = conn.find(ch)
        assert sub is not None
        sub.snapshot_pending = False  # so a re-snapshot shows as a flip back to pending
        reply = _ctl(conn, ch, {key: value})
        if families is None or ch.split(".")[0] in families:
            resnap = key in _RESNAPSHOT
            assert reply["t"] == "ctl_ok", (ch, key, reply)
            assert sub.snapshot_pending is resnap and ("resnapshot" in reply["p"]) is resnap, ch
            sub.snapshot_pending = False
            again = _ctl(conn, ch, {key: value})  # the same value again: the effective one is kept
            assert again["t"] == "ctl_ok" and "resnapshot" not in again["p"], (ch, key)
            assert sub.snapshot_pending is False, (ch, key)
        else:
            assert _refusal(reply) == (False, "invalid_options", key), (ch, reply)
            assert sub.snapshot_pending is False, (ch, key)


def test_a_the_ctl_matrix_has_a_sample_topic_for_every_public_family() -> None:
    public = {name for name, fam in FAMILIES.items() if not fam.private}
    assert {ch.split(".")[0] for ch in _TOPICS} == public, "add a sample topic to _TOPICS"


@pytest.mark.parametrize(("key", "value"), _OTHER_KEYS.items())
def test_a_ctl_refuses_any_other_key_naming_it_and_changes_nothing(key: str, value: Any) -> None:
    opts = {"metrics": ["cvd"], "bar_type": "time", "param": "5"}  # `sub` options, not `ctl` keys
    conn = _owner()
    assert _sub(conn, {"ch": "metrics.BTCUSDT", "opts": opts})[0]["ok"]
    sub = conn.find("metrics.BTCUSDT")
    assert sub is not None
    before = (dict(sub.opts), dict(sub.effective), sub.snapshot_pending)
    assert _refusal(_ctl(conn, "metrics.BTCUSDT", {key: value})) == (False, "invalid_options", key)
    assert (sub.opts, sub.effective, sub.snapshot_pending) == before


def test_a_ctl_for_the_implicit_system_topic_is_not_subscribed() -> None:
    conn = _owner()
    assert _sub(conn, "system")[0]["ok"]  # a `sub` of it is accepted, yet it is not held (§6.2)
    assert conn.by_id == {}
    reply = _ctl(conn, "system", {"throttle_ms": 500})
    assert (reply["t"], reply["p"]["code"]) == ("err", "not_subscribed")


@pytest.mark.parametrize(("family", "ms"), [("ticker", 250), ("liquidations", 500)])
def test_b_the_two_shapes_of_a_family_share_one_default_throttle(family: str, ms: int) -> None:
    results = _sub(_owner(), family, f"{family}.BTCUSDT")
    assert [(r["ok"], r["effective"]["throttle_ms"]) for r in results] == [(True, ms)] * 2


def test_c_no_topic_takes_params() -> None:
    opts = {"metrics": ["adx"], "params": {"adx": {"period": 14}}}
    (result,) = _sub(_owner(), {"ch": "metrics.BTCUSDT", "opts": opts})
    assert _refusal(result) == (False, "invalid_options", "params")


_SCOPED: Final = ("orders", "positions", "executions", "wallet", "trade_groups", "rules")


def test_d_exchange_account_ids_is_an_option_of_exactly_the_account_scoped_families() -> None:
    scoped = {f.family for f in FAMILIES.values() if f.account_scoped}
    with_accounts = {f.family for f in FAMILIES.values() if "exchange_account_ids" in f.options}
    assert scoped == with_accounts == set(_SCOPED)


@pytest.mark.parametrize("family", _SCOPED)
@pytest.mark.parametrize("who", [_owner, _manager])
def test_d_an_account_scoped_topic_needs_exchange_account_ids(
    family: str, who: Callable[[], ConnectionAuthz]
) -> None:
    conn = who()
    for entry in (family, {"ch": family, "opts": {"throttle_ms": 100}}):
        (result,) = _sub(conn, entry)
        assert _refusal(result) == (False, "account_scope_denied", None), entry
        assert result["error"]["message"] == "None of the requested accounts are in scope."
    (empty,) = _sub(conn, {"ch": family, "opts": {"exchange_account_ids": []}})
    assert _refusal(empty) == (False, "invalid_options", "exchange_account_ids")  # not "absent"
    assert conn.by_id == {}
    (result,) = _sub(conn, {"ch": family, "opts": {"exchange_account_ids": [ACC]}})
    assert result["ok"] and result["effective"]["exchange_account_ids"] == [ACC]


@pytest.mark.parametrize("family", ["alerts", "recorder"])
def test_d_the_user_scoped_and_unscoped_private_topics_refuse_accounts(family: str) -> None:
    assert _sub(_owner(), family)[0]["ok"]
    (result,) = _sub(_owner(), {"ch": family, "opts": {"exchange_account_ids": [ACC]}})
    assert _refusal(result) == (False, "invalid_options", "exchange_account_ids")


def test_e_the_json_subprotocol_needs_no_capability_to_ask_for_binary() -> None:
    world = _World()
    with world.client, world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        hello = {"capabilities": [], "encodings": ["structured"]}  # claims nothing: not read
        ws.send_json({"t": "hello", "id": "h", "p": hello})
        assert _recv(ws)["t"] == "welcome"
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "good"}})
        assert _recv(ws)["t"] == "auth_ok"
        topics = [
            {"ch": "book.BTCUSDT.50", "opts": {"encoding": "binary"}},
            {"ch": "book.BTCUSDT.200"},
            {"ch": "profile.BTCUSDT.volume", "opts": {"encoding": "binary"}},
        ]
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": topics}})
        results = _recv(ws)["p"]["results"]
    assert [(r["ok"], r["effective"]["encoding"]) for r in results[:2]] == [(True, "binary")] * 2
    assert _refusal(results[2]) == (False, "encoding_unsupported", "encoding")


@pytest.mark.parametrize(
    "entry",
    [
        {"ch": "ticker.BTCUSDT", "opts": {"symbols": ["ETHUSDT"]}},
        {"ch": "liquidations.BTCUSDT", "opts": {"symbols": ["ETHUSDT"]}},
        {"ch": "liquidations", "opts": {"symbols": ["BTCUSDT"], "cluster_window_ms": 100}},
    ],
)
def test_f_an_option_of_the_other_shape_is_accepted_and_echoed(entry: dict[str, Any]) -> None:
    (result,) = _sub(_owner(), entry)
    assert result["ok"]
    assert {k: result["effective"][k] for k in entry["opts"]} == entry["opts"]


def test_f_symbols_on_a_per_symbol_shape_serve_the_named_symbol_and_count_toward_the_cap() -> None:
    conn = _owner()
    assert _sub(conn, {"ch": "ticker.BTCUSDT", "opts": {"symbols": ["ETHUSDT"]}})[0]["ok"]
    sub = conn.find("ticker.BTCUSDT")
    assert sub is not None
    assert sub.upstream == (("BTCUSDT", "ticker", ()),)  # the symbol in the name, not `symbols`
    assert sub.symbols == {"BTCUSDT", "ETHUSDT"}
    conn = _owner()
    others = [f"S{i:02d}USDT" for i in range(40)]
    (refused,) = _sub(conn, {"ch": "ticker.BTCUSDT", "opts": {"symbols": others}})
    assert _refusal(refused) == (False, "subscription_limit", None)
    assert _sub(conn, {"ch": "ticker.BTCUSDT", "opts": {"symbols": others[:39]}})[0]["ok"]


#: The series and labels read before and after: ticker/ok results, unknown/unknown_topic results,
#: the depth histogram's observations and sum.
_READ: Final[tuple[tuple[str, dict[str, str]], ...]] = (
    ("cv_ws_subscribe_total", {"topic": "ticker", "result": "ok"}),
    ("cv_ws_subscribe_total", {"topic": "unknown", "result": "unknown_topic"}),
    ("cv_ws_client_topics_depth_count", {}),
    ("cv_ws_client_topics_depth_sum", {}),
)


def _readings() -> list[float]:
    return [REGISTRY.get_sample_value(name, labels) or 0.0 for name, labels in _READ]


def test_g_sub_results_count_by_family_and_the_depth_is_observed_after_each_frame() -> None:
    conn = _owner()
    before = _readings()
    _sub(conn, "ticker.BTCUSDT", "nope.BTCUSDT")
    after_sub = _readings()
    assert [a - b for a, b in zip(after_sub, before, strict=True)] == [1, 1, 1, 1]  # holds 1 sub
    frame = {"t": "unsub", "id": "c-3", "p": {"topics": ["ticker.BTCUSDT"]}}
    assert handle_unsub(conn, frame, 7)["t"] == "unsub_ok"
    after_unsub = _readings()
    assert [a - b for a, b in zip(after_unsub, after_sub, strict=True)] == [0, 0, 1, 0]  # holds 0
