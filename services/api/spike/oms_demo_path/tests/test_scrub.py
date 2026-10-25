# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""Outputs are scrubbed before they are written (#843 A4 brief item 7). Written red first.

The property: whatever identifiers are seeded into the corpus's shapes (the key id, a signature,
the UID, the account id, the `api_keys` id, `orderId`, `orderLinkId`, `execId`), in their own
fields, in free text, in headers, in an `auth` frame or nested in unknown fields, none survives
the scrubber, and no byte reaches a file before it has passed through it.
"""

from __future__ import annotations

import gzip
import json
import string
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from spike.oms_demo_path.outputs import FRAMES_PER_TOPIC, RunOutputs
from spike.oms_demo_path.scrub import ID_KEYS, LeakDetected, Scrubber
from tests._corpus import frames, rest

_ALNUM = string.ascii_letters + string.digits
_UUIDS = st.uuids().map(str)
_IDS = st.one_of(_UUIDS, st.text(alphabet=_ALNUM, min_size=12, max_size=24))
_LINKS = st.text(alphabet=_ALNUM, min_size=21, max_size=21).map(lambda g: f"cvd-0{g}-ab12-00en")
_UIDS = st.integers(min_value=10**7, max_value=10**10).map(str)
_KEYS = st.text(alphabet=_ALNUM, min_size=18, max_size=18)
_SIGS = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)
_SHAPES = (
    "create",
    "execution",
    "order",
    "fast",
    "position",
    "execution_list",
    "auth",
    "auth_reply",
    "request",
    "nested",
)


def _push(name: str) -> dict[str, Any]:
    [frame] = frames(f"ws/private-{name}.jsonl")
    decoded: dict[str, Any] = json.loads(frame)
    return decoded


def _payload(shape: str, s: dict[str, str]) -> dict[str, Any]:
    """A corpus shape with the seeded identifiers where the venue puts them, and echoed in free
    text: every identifier the record itself carries, and the key id and signature the request
    went out with (an identifier no record has carried yet cannot be known, and is not echoed)."""
    fills = shape in ("execution", "fast", "execution_list")
    echo = f"seen {s['order']} {s['link']} {s['key']} {s['signature']}"
    echo += f" {s['exec']} {s['uid']}" if fills else f" {s['uid']}"
    if shape == "create":
        body = rest("rest/trading-create-reply.json")
        result = {**body["result"], "orderId": s["order"], "orderLinkId": s["link"]}
        return {**body, "result": result, "retMsg": f"OK {s['order']} {s['link']}"}
    if shape in ("execution", "order", "fast", "position"):
        name = {"fast": "execution-fast"}.get(shape, shape)
        frame = _push(name)
        row = {**frame["data"][0], "orderId": s["order"], "orderLinkId": s["link"]}
        if shape in ("execution", "fast"):
            row["execId"] = s["exec"]
        row["comment"] = echo  # an unknown free-text field
        return {**frame, "id": f"{s['uid']}_BTCUSDT_1", "data": [row]}
    if shape == "execution_list":
        body = rest("rest/trading-execution-list.json")
        row = {**body["result"]["list"][0], "execId": s["exec"], "orderId": s["order"]}
        row["orderLinkId"] = s["link"]
        cursor = f"page_args%3D{s['order']}%26"
        result = {**body["result"], "list": [row], "nextPageCursor": cursor}
        return {**body, "result": result, "retMsg": echo.replace(s["uid"], "")}
    if shape == "auth":
        return {"op": "auth", "args": [s["key"], 1_790_000_000_000, s["signature"]]}
    if shape == "auth_reply":
        return {**_push("auth-ok"), "ret_msg": echo}
    if shape == "request":
        return {
            "method": "POST",
            "path": "/v5/order/create",
            "headers": {"X-BAPI-API-KEY": s["key"], "X-BAPI-SIGN": s["signature"]},
            "body": {"orderLinkId": s["link"], "symbol": "BTCUSDT"},
        }
    return {
        "wrapper": [{"deep": {"orderId": s["order"], "execId": s["exec"]}}],
        "account_id": s["account"],
        "key_ref": s["key_ref"],
        "text": f"account {s['account']} key {s['key_ref']} order {s['order']} {s['exec']}",
    }


def _harness_scrubber(s: dict[str, str]) -> Scrubber:
    """What the harness registers before anything is written: the account and key it was given,
    and the request's key id (the recording transport reads it from the request's header)."""
    scrubber = Scrubber()
    for value in (s["account"], s["key_ref"], s["key"]):
        scrubber.secret(value)
    return scrubber


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    shape=st.sampled_from(_SHAPES),
    order=_IDS,
    link=_LINKS,
    exec_id=_IDS,
    uid=_UIDS,
    key=_KEYS,
    signature=_SIGS,
    account=_UUIDS,
    key_ref=_UUIDS,
)
def test_no_seeded_identifier_survives_the_scrubber(
    shape: str,
    order: str,
    link: str,
    exec_id: str,
    uid: str,
    key: str,
    signature: str,
    account: str,
    key_ref: str,
) -> None:
    seeds = {
        "order": order,
        "link": link,
        "exec": exec_id,
        "uid": uid,
        "key": key,
        "signature": signature,
        "account": account,
        "key_ref": key_ref,
    }
    assume(len(set(seeds.values())) == len(seeds))
    assume(not any(a != b and a in b for a in seeds.values() for b in seeds.values()))
    blank = json.dumps(_payload(shape, dict.fromkeys(seeds, "~")))
    assume(not any(value in blank for value in seeds.values()))
    scrubber = _harness_scrubber(seeds)
    payload = _payload(shape, seeds)
    text = (
        json.dumps(scrubber.frame(json.dumps(payload)))
        if shape.startswith("auth")
        else scrubber.dumps(payload, transient=(signature,))
    )
    for name, value in seeds.items():
        assert value not in text, f"{name} survived in {shape}"


@pytest.mark.parametrize("field", sorted(ID_KEYS))
def test_every_id_class_is_replaced_by_a_stable_per_run_token(field: str) -> None:
    scrubber = Scrubber()
    first = scrubber.scrub({field: ORDER})
    again = scrubber.scrub({"x": [{field: ORDER}]})
    other = scrubber.scrub({field: ACCOUNT})
    assert isinstance(first, dict) and isinstance(again, dict) and isinstance(other, dict)
    token = first[field]
    assert token.startswith(ID_KEYS[field] + "#")
    assert again["x"][0][field] == token
    assert other[field] != token


def test_an_empty_id_stays_empty_and_numbers_and_prices_are_kept() -> None:
    scrubber = Scrubber()
    row = {"orderLinkId": "", "execPrice": "63110.0", "execQty": "0.001", "seq": 4688002127}
    assert scrubber.scrub(row) == row


def test_auth_frames_are_dropped_whole_and_headers_never_written() -> None:
    scrubber = Scrubber()
    assert scrubber.frame(json.dumps({"op": "auth", "args": ["k" * 18, 1, "a" * 64]})) is None
    assert scrubber.frame(frames("ws/private-auth-ok.jsonl")[0]) is None
    scrubbed = scrubber.scrub({"headers": {"X-BAPI-SIGN": "a" * 64}, "X-BAPI-API-KEY": "k" * 18})
    assert scrubbed == {}


def test_a_push_id_teaches_the_scrubber_the_uid() -> None:
    scrubber = Scrubber()
    scrubber.scrub({"id": "386825804_BTCUSDT_140612148849382"})
    assert "386825804" not in scrubber.dumps({"retMsg": "uid 386825804 refused"})


def test_check_refuses_text_that_still_holds_a_registered_value() -> None:
    scrubber = Scrubber()
    scrubber.secret("0f8e2b6c-3d4a-4b5c-9e7f-1a2b3c4d5e6f")
    with pytest.raises(LeakDetected):
        scrubber.check('{"x": "0f8e2b6c-3d4a-4b5c-9e7f-1a2b3c4d5e6f"}')
    scrubber.check('{"x": "nothing of ours"}')


def test_a_short_value_is_never_registered() -> None:
    scrubber = Scrubber()
    scrubber.secret("12345")
    assert scrubber.dumps({"text": "12345"}) == '{"text":"12345"}'


# -- the writer: the scrub runs before a byte reaches the file ----------------------------------


class _Recorder:
    """Stands in for the file system: every write the outputs make, as it would reach a file."""

    def __init__(self) -> None:
        self.writes: list[tuple[Path, bytes, bool]] = []

    def __call__(self, path: Path, data: bytes, append: bool) -> None:
        self.writes.append((path, data, append))

    def plain(self) -> list[tuple[Path, bytes]]:
        """Each write as the file would read back: a `.gz` fixture decompressed."""
        return [
            (path, gzip.decompress(data) if path.suffix == ".gz" else data)
            for path, data, _ in self.writes
        ]

    def text(self) -> str:
        return "".join(data.decode("utf-8", "replace") for _, data in self.plain())


ORDER = "0f8e2b6c-3d4a-4b5c-9e7f-1a2b3c4d5e6f"
ACCOUNT = "6c2d0e3f-8041-4b7c-9d5e-3f4a5b6c7d8e"


def test_the_scrub_runs_before_a_line_reaches_the_file(tmp_path: Path) -> None:
    recorder = _Recorder()
    scrubber = Scrubber()
    scrubber.secret(ACCOUNT)
    outputs = RunOutputs(tmp_path / "run", scrubber, write=recorder)
    outputs.event("rest", reply={"result": {"orderId": ORDER}}, note=f"for {ACCOUNT}")
    outputs.rest_fixture("create_0", {"result": {"orderId": ORDER}, "retMsg": ORDER})
    outputs.frame("order", json.dumps({"topic": "order", "data": [{"orderId": ORDER}]}))
    outputs.write_summary({"account": ACCOUNT, "order": ORDER})
    outputs.write_metrics(f"# HELP x {ORDER}\n")
    outputs.close()
    assert recorder.writes, "nothing was written at all"
    for _path, data in recorder.plain():
        assert ORDER.encode() not in data and ACCOUNT.encode() not in data
    names = {path.name for path, _, _ in recorder.writes}
    assert {"events.jsonl", "summary.json", "metrics.prom"} <= names
    assert any(name.startswith("private_order") for name in names)


def test_a_line_the_scrub_misses_is_refused_and_never_written(tmp_path: Path) -> None:
    recorder = _Recorder()
    scrubber = Scrubber()
    scrubber.secret(ACCOUNT)
    outputs = RunOutputs(tmp_path / "run", scrubber, write=recorder)
    scrubber.scrub = lambda value, transient=(): value  # type: ignore[method-assign]
    assert outputs.event("leak", note=f"for {ACCOUNT}") is False
    outputs.write_summary({"account": ACCOUNT})
    assert ACCOUNT not in recorder.text()
    assert outputs.refused == 2


def test_the_outputs_directory_and_files_are_private(tmp_path: Path) -> None:
    outputs = RunOutputs(tmp_path / "run", Scrubber())
    outputs.event("start")
    outputs.write_summary({"ok": True})
    outputs.close()
    assert oct((tmp_path / "run").stat().st_mode & 0o777) == "0o700"
    for name in ("events.jsonl", "summary.json"):
        assert oct((tmp_path / "run" / name).stat().st_mode & 0o777) == "0o600"
    [line] = (tmp_path / "run" / "events.jsonl").read_text().splitlines()
    assert json.loads(line)["kind"] == "start"


def test_seeded_uuids_are_valid() -> None:  # the strategies' own shapes
    assert UUID(ORDER) and UUID(ACCOUNT)


def test_scrubbing_twice_changes_nothing_and_learns_no_token() -> None:
    scrubber = Scrubber()
    row = {"orderId": ORDER, "orderLinkId": "cvd-0aaaaaaaaaaaaaaaaaaaaa-ab12-00en", "retMsg": ORDER}
    once = scrubber.scrub(row)
    assert scrubber.scrub(once) == once
    scrubber.check(json.dumps(once))  # no token is ever taken for an identifier


def test_fixture_names_are_plain_and_frames_are_bounded_per_topic(tmp_path: Path) -> None:
    outputs = RunOutputs(tmp_path / "run", Scrubber())
    with pytest.raises(ValueError, match="fixture name"):
        outputs.rest_fixture("../escape", {})
    outputs.frame("no such/topic", "{}")
    for _ in range(FRAMES_PER_TOPIC + 5):
        outputs.frame("order", '{"topic":"order","data":[]}')
    outputs.frame("op_auth", json.dumps({"op": "auth", "success": True}))
    outputs.close()
    fixtures = tmp_path / "run" / "fixtures"
    kept = gzip.decompress((fixtures / "private_order.jsonl.gz").read_bytes()).splitlines()
    assert len(kept) == FRAMES_PER_TOPIC and outputs.frames_seen["order"] == FRAMES_PER_TOPIC + 5
    assert sorted(p.name for p in fixtures.iterdir()) == ["private_order.jsonl.gz"]


def test_a_frame_or_metrics_text_the_check_refuses_is_never_written(tmp_path: Path) -> None:
    recorder = _Recorder()
    scrubber = Scrubber()
    scrubber.secret(ACCOUNT)
    scrubber.secret(None)
    outputs = RunOutputs(tmp_path / "run", scrubber, write=recorder)
    scrubber.scrub = lambda value, transient=(): value  # type: ignore[method-assign]
    outputs.frame("order", json.dumps({"topic": "order", "note": ACCOUNT}))
    outputs.write_metrics(f"# HELP x {ACCOUNT}\n")
    outputs.close()
    assert ACCOUNT not in recorder.text() and outputs.refused == 2


def test_an_unreadable_frame_is_never_kept() -> None:
    assert Scrubber().frame("{not json") is None
