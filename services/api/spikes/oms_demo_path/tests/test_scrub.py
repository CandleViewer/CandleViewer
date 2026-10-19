"""The scrubber and the fixture sink: a capture holding fake key-shaped values comes out clean,
and a read endpoint keeps one capture per kind of reply.

Fake values are derived at run time from fixed labels (no secret-shaped literal in the source).
Field names follow the documented Bybit v5 shapes (`docs/research/06-bybit-api.md` §10).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from candleviewer.domain.order_link import OUR_ID
from candleviewer.domain.primitives import AccountId
from candleviewer.secrets import Secret
from spikes.oms_demo_path.capture import FixtureSink, RestRecorder, labelled
from spikes.oms_demo_path.safety import new_link
from spikes.oms_demo_path.scrub import MASK, LeakError, Scrubber


def _fake(label: str, length: int) -> str:
    """A key-shaped run of letters and digits, derived from `label`."""
    value = "k" + hashlib.sha256(label.encode()).hexdigest()[: length - 1]
    assert any(c.isdigit() for c in value)
    return value


FAKE_ID = _fake("fake key id", 20)
FAKE_LONG = _fake("fake signing value", 36)
FAKE_MAC = hashlib.sha256(b"fake mac").hexdigest()
FAKE_UID = "73914520"
ORDER, EXEC = str(uuid4()), str(uuid4())
LINK = new_link(AccountId(uuid4()), "entry")


def _capture() -> dict[str, Any]:
    order = {"orderId": ORDER, "orderLinkId": LINK, "orderStatus": "PartiallyFilled"}
    order |= {"cumExecQty": "0.02", "updatedTime": "1760000000123", "symbol": "ETHUSDT"}
    execution = {"orderId": ORDER, "orderLinkId": LINK, "execId": EXEC, "execQty": "0.02"}
    return {
        "frames": [
            {"op": "auth", "success": True, "conn_id": "c" + FAKE_ID[1:]},
            {"id": "msg-1", "topic": "order", "creationTime": 1760000000125, "data": [order]},
            {"topic": "execution", "data": [execution | {"execTime": "1760000000120"}]},
        ],
        "result": {"uid": int(FAKE_UID), "userID": FAKE_UID, "apiKey": FAKE_ID},
        "headers": {"X-BAPI-API-KEY": FAKE_ID, "X-BAPI-SIGN": FAKE_MAC, "sign": FAKE_MAC},
        "secret": FAKE_LONG,
        "retMsg": f"orderLinkId {LINK} is duplicate; key {FAKE_ID}",
    }


def _scrubber() -> Scrubber:
    scrubber = Scrubber([Secret(FAKE_ID)])
    scrubber.add_known(FAKE_UID)
    return scrubber


def test_scrubbed_capture_holds_no_fake_value_and_passes_the_leak_checks() -> None:
    text = _scrubber().dumps(_capture())
    for value in (FAKE_ID, FAKE_LONG, FAKE_MAC, FAKE_UID, ORDER, EXEC, LINK):
        assert value not in text
    assert _scrubber().leaks(text) == []


def test_stand_ins_keep_shape_and_agree_across_frames() -> None:
    out = _scrubber().scrub(_capture())
    order, execution = out["frames"][1]["data"][0], out["frames"][2]["data"][0]
    assert order["orderId"] == execution["orderId"] and str(UUID(order["orderId"]))
    assert OUR_ID.fullmatch(order["orderLinkId"]) and order["orderLinkId"][-2:] == "en"
    assert order["orderLinkId"] in out["retMsg"] and out["secret"] == MASK
    assert out["result"]["uid"] == 100_000_001 and out["result"]["apiKey"] == MASK
    assert order["cumExecQty"] == "0.02" and order["orderStatus"] == "PartiallyFilled"


@pytest.mark.parametrize(
    ("value", "check"),
    [
        ({"note": FAKE_MAC}, "hex-signature"),
        ({"note": FAKE_ID}, "key-shape"),
        ({"note": FAKE_LONG}, "key-shape"),
    ],
)
def test_dumps_refuses_a_leftover_secret_shape(value: dict[str, str], check: str) -> None:
    with pytest.raises(LeakError) as caught:
        Scrubber().dumps(value)
    assert check in caught.value.patterns


def test_check_refuses_a_known_value_in_raw_text() -> None:
    with pytest.raises(LeakError) as caught:
        _scrubber().check(f"prefix-{FAKE_UID}-suffix")
    assert caught.value.patterns == ["known-value"]


def test_fixture_sink_writes_the_corpus_layout(tmp_path: Path) -> None:
    scrubber = _scrubber()
    recorder = RestRecorder(scrubber)
    request = httpx.Request("POST", "https://api-demo.bybit.com/v5/order/create", json={})
    reply = {"retCode": 110072, "retMsg": f"duplicate {LINK}", "result": {}, "time": 1}
    with labelled("duplicate"):
        recorder(
            request, 200, httpx.Headers({"X-Bapi-Limit": "10"}), json.dumps(reply).encode(), 0.1
        )
    sink = FixtureSink(
        tmp_path, symbol="ETHUSDT", mode="orders", date="2026-10-19", scrubber=scrubber
    )
    sink.ws_frame(_capture()["frames"][1])
    entries = sink.write(recorder.captures)
    root = tmp_path / "bybit" / "2026-10-19"
    assert [e["path"] for e in entries] == [
        "rest/order_create_110072.json",
        "ws/private_orders_ETHUSDT.jsonl",
    ]
    assert entries[0]["headers"] == {"x-bapi-limit": "10"}
    manifest = json.loads((root / "manifest.json").read_text())
    required = {"path", "symbol", "stream", "host", "capture_date", "notable_event"}
    assert all(required <= set(e) for e in manifest["fixtures"])
    written = "".join(p.read_text() for p in root.rglob("*") if p.is_file())
    assert LINK not in written and (root / "README.e29-k01.md").exists()


def _read(recorder: RestRecorder, path: str, rows: list[dict[str, Any]]) -> None:
    """One `GET` reply listing `rows`, as the demo REST host answers a read."""
    request = httpx.Request("GET", f"https://api-demo.bybit.com{path}")
    reply = {"retCode": 0, "retMsg": "OK", "result": {"category": "linear", "list": rows}}
    recorder(request, 200, httpx.Headers(), json.dumps(reply).encode(), 0.1)


def test_read_captures_keep_the_populated_reply_beside_the_empty_one(tmp_path: Path) -> None:
    """The preflight reads an empty order list and a flat position first; the rows the
    integration suites need (a resting order, an open position) are kept as their own files."""
    scrubber = _scrubber()
    recorder = RestRecorder(scrubber)
    resting = {"orderId": ORDER, "orderLinkId": LINK, "orderStatus": "New", "qty": "0.005"}
    position = {"symbol": "ETHUSDT", "side": "", "size": "0", "positionValue": ""}
    _read(recorder, "/v5/order/realtime", [])
    _read(recorder, "/v5/position/list", [position])
    _read(recorder, "/v5/order/realtime", [resting])
    _read(recorder, "/v5/position/list", [position | {"side": "Buy", "size": "0.005"}])
    _read(recorder, "/v5/order/realtime", [resting | {"orderStatus": "PartiallyFilled"}])
    _read(
        recorder,
        "/v5/order/realtime",
        [resting | {"orderLinkId": new_link(AccountId(uuid4()), "entry")}],
    )
    sink = FixtureSink(
        tmp_path, symbol="ETHUSDT", mode="orders", date="2026-10-19", scrubber=scrubber
    )
    assert sorted(e["path"] for e in sink.write(recorder.captures)) == [
        "rest/order_realtime_0_New.json",
        "rest/order_realtime_0_PartiallyFilled.json",
        "rest/order_realtime_0_empty.json",
        "rest/position_list_0_flat.json",
        "rest/position_list_0_open.json",
    ]


def test_a_known_uid_counts_only_as_a_whole_number() -> None:
    """A UID inside a longer number (a timestamp) is neither masked nor refused; standing alone,
    or touching letters, it is both."""
    scrubber = _scrubber()
    stamp = f"17{FAKE_UID}123"
    assert scrubber.mask_known(f"uid {FAKE_UID} at {stamp}") == f"uid {MASK} at {stamp}"
    assert scrubber.mask_known(f"key={FAKE_ID}") == f"key={MASK}"
    assert scrubber.leaks(stamp) == [] and scrubber.leaks(f"uid{FAKE_UID}") == ["known-value"]
