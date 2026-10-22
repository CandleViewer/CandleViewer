"""Drift check of the docs-transcribed order-path shapes (G-8, #2877, ruling R2) and private-stream
frames (G-8b, #3963, ruling 11).

A transcription (`source: docs-transcribed` in a corpus manifest) stands in for a recording that
does not exist yet. The moment a recording of the same route and return code lands (E29-K01,
#843, in any dated corpus directory), its field paths and JSON types must agree with the
transcription's, or this test fails naming them; the recording then replaces the transcription.
The route is read from the manifest's `stream` label, `<METHOD> /v5/<path>` (a label without the
method matches on the path), so a recording labelled another way is still compared, and a REST
recording whose label names no route fails here rather than going unchecked. A field the
recording cannot show (rows of an empty list) is not a disagreement, and an error-row
transcription, which holds only the error table's code and text, is compared on those keys only.

The private stream's frames (`ws/private-*.jsonl`) are compared the same way, every frame of a
file at once, with every WS recording of the same private topic or reply: the label is the
topic as subscribed (`order.linear`; its all-in-one name `order` is the same topic) or
`op <name>` for a reply, and a recording may be `.jsonl` or `.jsonl.gz` (OQ-7). A WS recording
that holds a private push or a reply but whose label pairs with no transcription fails here.
"""

from __future__ import annotations

import gzip
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tests._corpus import CORPUS_ROOT, rest

TRANSCRIBED = "docs-transcribed"
#: A REST route in a stream label: an optional method, then the `/v5/` path.
_ROUTE = re.compile(r"(?:\b(GET|POST)\s+)?(/v5/[A-Za-z0-9/_-]+)")

type Route = tuple[str | None, str]


def _paths(value: Any, prefix: str = "") -> dict[str, set[str]]:
    """Every field path of `value` with its JSON types (`list[]` for array items)."""
    out: dict[str, set[str]] = {}

    def walk(node: Any, path: str) -> None:
        kind = (
            "null" if node is None else "boolean" if isinstance(node, bool)
            else "number" if isinstance(node, int | float) else "string" if isinstance(node, str)
            else "array" if isinstance(node, list) else "object"
        )  # fmt: skip
        out.setdefault(path, set()).add(kind)
        if isinstance(node, dict):
            for key, child in node.items():
                walk(child, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for child in node:
                walk(child, f"{path}[]")

    walk(value, prefix)
    return out


def disagreements(transcribed: Any, recorded: Any, *, own_keys_only: bool = False) -> list[str]:
    """Where a recording differs from a transcription of its shape; with `own_keys_only`, a
    field the transcription does not hold is no disagreement (an error-table row)."""
    want, got = _paths(transcribed), _paths(recorded)
    extra = [] if own_keys_only else sorted(set(got) - set(want))
    out = [f"recorded only: {p}" for p in extra]
    for path in sorted(set(want) - set(got)):
        if "[]" in path and path[: path.rindex("[]") + 2] not in got:
            continue  # an empty array in the recording: it shows none of its items
        parent = path.rsplit(".", 1)[0] if "." in path else ""
        if not parent or any(p.startswith(parent + ".") for p in got):
            out.append(f"transcribed only: {path}")  # the recording shows that object
    out += [
        f"retyped: {p} {sorted(want[p])} -> {sorted(got[p])}"
        for p in sorted(set(want) & set(got))
        if not got[p] <= want[p] and "null" not in got[p] | want[p]
    ]
    return out


def _entries(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    for manifest in sorted(root.glob("*/manifest.json")):
        for entry in json.loads(manifest.read_text(encoding="utf-8"))["fixtures"]:
            out.append((manifest.parent / entry["path"], entry))
    return out


def route(stream: str) -> Route | None:
    """The method and `/v5/` path a stream label names, or `None` when it names no route."""
    found = _ROUTE.search(stream)
    return None if found is None else (found.group(1), found.group(2))


def _same_route(one: Route, other: Route) -> bool:
    return one[1] == other[1] and (None in (one[0], other[0]) or one[0] == other[0])


def _code(path: Path) -> object:
    body = _load(path)
    return body.get("retCode") if isinstance(body, dict) else None


def _recordings(entries: list[tuple[Path, dict[str, Any]]]) -> list[tuple[Path, dict[str, Any]]]:
    """The REST bodies recorded from the venue: neither transcribed nor built (#1778 A)."""
    out = []
    for path, entry in entries:
        source = str(entry.get("source", ""))
        transcribed = source == TRANSCRIBED or source.startswith("documented-shape")
        if not transcribed and path.suffix == ".json" and path.parent.name == "rest":
            out.append((path, entry))
    return out


def drift(root: Path) -> dict[str, list[str]]:
    """Per transcription, its disagreements with every recording of its route and code."""
    entries = _entries(root)
    recordings = _recordings(entries)
    out: dict[str, list[str]] = {}
    for path, entry in entries:
        named = route(str(entry["stream"])) if entry.get("source") == TRANSCRIBED else None
        if named is None:
            continue
        code = _code(path)
        for recorded, recorded_entry in recordings:
            recorded_route = route(str(recorded_entry["stream"]))
            if recorded_route is None or not _same_route(named, recorded_route):
                continue
            if _code(recorded) != code:
                continue
            found = disagreements(_load(path), _load(recorded), own_keys_only=code != 0)
            if found:
                where = f"{recorded.parent.parent.name}/rest/{recorded.name}"
                out[f"{path.name} vs {where}"] = found
    return out


def unrouted(root: Path) -> list[str]:
    """The REST recordings whose stream label names no route: the check could not see them."""
    return [
        f"{path.parent.parent.name}/rest/{path.name}"
        for path, entry in _recordings(_entries(root))
        if route(str(entry["stream"])) is None
    ]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# -- the private stream's frames (G-8b, #3963) ----------------------------------------------------

#: The private stream's transcriptions, each one documented frame (`build_corpus._DOCS_FRAMES`).
WS_TRANSCRIBED = {
    "ws/private-auth-ok.jsonl",
    "ws/private-execution-fast.jsonl",
    "ws/private-execution.jsonl",
    "ws/private-order.jsonl",
    "ws/private-pong.jsonl",
    "ws/private-position.jsonl",
    "ws/private-subscribe-ok.jsonl",
    "ws/private-wallet.jsonl",
}
#: The private topics the adapter subscribes, all-in-one names; a category suffix is one topic.
_PRIVATE_TOPICS = frozenset({"execution.fast", "execution", "order", "position", "wallet"})
_CATEGORIES = (".linear", ".inverse", ".spot", ".option")
_REPLIES = frozenset({"auth", "subscribe", "pong"})


def ws_label(stream: str) -> str | None:
    """The private topic or reply a WS label names (`order.linear` and `order` are `order`;
    `op auth` is itself), or `None` when it names neither."""
    if stream.startswith("op "):
        return stream if stream[3:] in _REPLIES else None
    for suffix in _CATEGORIES:
        stream = stream.removesuffix(suffix)
    return stream if stream in _PRIVATE_TOPICS else None


def _frame_label(frame: Any) -> str | None:
    """What one frame is: a private topic's push, a reply, or `None` (public data or other)."""
    if not isinstance(frame, dict):
        return None
    if isinstance(frame.get("topic"), str):
        return ws_label(frame["topic"])
    op = frame.get("op")
    return f"op {op}" if isinstance(op, str) and op in _REPLIES else None


def _frames(path: Path) -> list[Any]:
    """A WS file's frames, one per line: `.jsonl`, or `.jsonl.gz` as E29-K01 may commit it."""
    if path.suffix == ".gz":
        text = gzip.decompress(path.read_bytes()).decode("utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _ws(path: Path) -> bool:
    return path.parent.name == "ws" and (path.suffix == ".jsonl" or path.name.endswith(".jsonl.gz"))


def _ws_recordings(
    entries: list[tuple[Path, dict[str, Any]]],
) -> list[tuple[Path, dict[str, Any]]]:
    """The WS frames recorded from the venue: neither transcribed nor built (#1778 A)."""
    out = []
    for path, entry in entries:
        source = str(entry.get("source", ""))
        if _ws(path) and source != TRANSCRIBED and not source.startswith("documented-shape"):
            out.append((path, entry))
    return out


def _ws_transcriptions(entries: list[tuple[Path, dict[str, Any]]]) -> list[tuple[Path, str]]:
    return [
        (path, label)
        for path, entry in entries
        if entry.get("source") == TRANSCRIBED and _ws(path)
        if (label := ws_label(str(entry["stream"]))) is not None
    ]


def ws_drift(root: Path) -> dict[str, list[str]]:
    """Per WS transcription, its disagreements with every recording of its topic or reply."""
    entries = _entries(root)
    recordings = _ws_recordings(entries)
    out: dict[str, list[str]] = {}
    for path, label in _ws_transcriptions(entries):
        for recorded, entry in recordings:
            if ws_label(str(entry["stream"])) != label:
                continue
            found = disagreements(_frames(path), _frames(recorded))
            if found:
                out[f"{path.name} vs {recorded.parent.parent.name}/ws/{recorded.name}"] = found
    return out


def ws_unpaired(root: Path) -> list[str]:
    """The WS recordings that hold a private push or a reply but whose label pairs with no
    transcription: the check could not see them."""
    entries = _entries(root)
    labels = {label for _, label in _ws_transcriptions(entries)}
    return [
        f"{path.parent.parent.name}/ws/{path.name}"
        for path, entry in _ws_recordings(entries)
        if {_frame_label(f) for f in _frames(path)} - {None}
        and ws_label(str(entry["stream"])) not in labels
    ]


def test_every_ws_transcription_is_listed_with_its_source() -> None:
    entries = {e["path"]: e for _, e in _entries(CORPUS_ROOT) if e["path"] in WS_TRANSCRIBED}
    assert set(entries) == WS_TRANSCRIBED
    for entry in entries.values():
        assert entry["source"] == TRANSCRIBED and entry["retrieved"] == "2026-10-21"
        assert entry["source_url"].startswith("https://bybit-exchange.github.io/docs/v5/")
        assert entry["source_ref"].startswith("github.com/bybit-exchange/docs@19518b90fb36")
        assert entry["http_status"] is None and entry["host"] == "bybit-exchange.github.io"
    labels = sorted(str(ws_label(str(e["stream"]))) for e in entries.values())
    expected = ["execution", "execution.fast", "op auth", "op pong", "op subscribe", "order"]
    assert labels == sorted([*expected, "position", "wallet"])


def test_no_ws_recording_disagrees_with_a_transcription() -> None:
    assert ws_drift(CORPUS_ROOT) == {}


def test_every_private_ws_recording_pairs_with_a_transcription() -> None:
    assert ws_unpaired(CORPUS_ROOT) == []


def _write_ws(
    directory: Path, entries: Iterable[tuple[str, str, list[Any]]], stream: str = "order.linear"
) -> None:
    """A corpus directory: `(file, source, frames)` per entry under `ws/`, one stream label; a
    name ending `.gz` is written gzipped."""
    (directory / "ws").mkdir(parents=True)
    fixtures = []
    for name, source, frames in entries:
        text = "".join(json.dumps(frame) + "\n" for frame in frames)
        target = directory / "ws" / name
        if name.endswith(".gz"):
            target.write_bytes(gzip.compress(text.encode("utf-8")))
        else:
            target.write_text(text, encoding="utf-8")
        fixtures.append({"path": f"ws/{name}", "stream": stream, "source": source})
    (directory / "manifest.json").write_text(json.dumps({"fixtures": fixtures}), encoding="utf-8")


[ORDER] = _frames(CORPUS_ROOT / "2026-10-05" / "ws" / "private-order.jsonl")
[AUTH_OK] = _frames(CORPUS_ROOT / "2026-10-05" / "ws" / "private-auth-ok.jsonl")


def _pushed(**row: Any) -> dict[str, Any]:
    """A planted recording: the transcribed order push with `row`'s fields changed and the
    categorised topic (a test input, never a venue fact)."""
    first = {**ORDER["data"][0], **row}
    return {**ORDER, "topic": "order.linear", "data": [first]}


def test_a_ws_recording_that_adds_drops_or_retypes_a_field_is_caught(tmp_path: Path) -> None:
    changed = _pushed(newVenueField="x", qty=1)
    del changed["data"][0]["smpGroup"]
    _write_ws(tmp_path / "a", [("t.jsonl", TRANSCRIBED, [ORDER])])
    _write_ws(tmp_path / "b", [("r.jsonl", "capture (redacted)", [_pushed(), changed])])
    [found] = ws_drift(tmp_path).values()
    assert "recorded only: [].data[].newVenueField" in found
    assert "retyped: [].data[].qty ['string'] -> ['number', 'string']" in found
    assert "transcribed only: [].data[].smpGroup" not in found  # another frame shows it


def test_a_ws_recording_that_agrees_or_shows_no_rows_passes(tmp_path: Path) -> None:
    empty = {**ORDER, "data": []}
    _write_ws(
        tmp_path / "a",
        [
            ("t.jsonl", TRANSCRIBED, [ORDER]),
            ("same.jsonl", "capture (redacted)", [_pushed(), _pushed(orderLinkId="x")]),
            ("empty.jsonl", "capture (redacted)", [empty]),
        ],
    )
    assert ws_drift(tmp_path) == {}


def test_a_ws_recording_that_drops_a_field_from_every_frame_is_caught(tmp_path: Path) -> None:
    dropped = _pushed()
    del dropped["data"][0]["smpGroup"]
    _write_ws(tmp_path / "a", [("t.jsonl", TRANSCRIBED, [ORDER])])
    _write_ws(tmp_path / "b", [("r.jsonl", "capture", [dropped])])
    [found] = ws_drift(tmp_path).values()
    assert found == ["transcribed only: [].data[].smpGroup"]


def test_a_gzipped_recording_under_the_all_in_one_topic_is_still_compared(tmp_path: Path) -> None:
    """OQ-7: E29-K01 may commit `.jsonl.gz`; `order` and `order.linear` are one topic."""
    _write_ws(tmp_path / "a", [("t.jsonl", TRANSCRIBED, [ORDER])])
    _write_ws(tmp_path / "b", [("r.jsonl.gz", "capture", [_pushed(qty=1)])], stream="order")
    [found] = ws_drift(tmp_path).values()
    assert found == ["retyped: [].data[].qty ['string'] -> ['number']"]


def test_a_ws_recording_of_another_topic_or_reply_is_another_shape(tmp_path: Path) -> None:
    _write_ws(tmp_path / "a", [("t.jsonl", TRANSCRIBED, [ORDER])])
    _write_ws(tmp_path / "b", [("r.jsonl", "capture", [AUTH_OK | {"x": 1}])], stream="op auth")
    _write_ws(tmp_path / "c", [("p.jsonl", "capture", [_pushed(qty=1)])], stream="position.linear")
    assert ws_drift(tmp_path) == {}


def test_a_private_ws_recording_whose_label_pairs_with_nothing_is_reported(tmp_path: Path) -> None:
    """A private push or reply under a label no transcription names fails rather than going
    unchecked; a public recording is no concern of this check."""
    public = {"topic": "publicTrade.BTCUSDT", "data": []}
    _write_ws(tmp_path / "a", [("t.jsonl", TRANSCRIBED, [ORDER])])
    _write_ws(tmp_path / "b", [("r.jsonl", "capture", [_pushed()])], stream="private session")
    _write_ws(tmp_path / "c", [("p.jsonl", "capture", [public])], stream="publicTrade.BTCUSDT")
    _write_ws(tmp_path / "d", [("q.jsonl", "capture", [AUTH_OK])], stream="op auth")
    assert ws_unpaired(tmp_path) == ["b/ws/r.jsonl", "d/ws/q.jsonl"]


def test_no_recording_disagrees_with_a_transcription() -> None:
    assert drift(CORPUS_ROOT) == {}


def test_every_rest_recording_names_its_route() -> None:
    assert unrouted(CORPUS_ROOT) == []


def test_every_transcription_names_its_route() -> None:
    """A REST transcription names its route; a WS one its private topic or reply (G-8b)."""
    transcribed = [(p, e) for p, e in _entries(CORPUS_ROOT) if e.get("source") == TRANSCRIBED]
    rest = [str(e["stream"]) for p, e in transcribed if p.parent.name == "rest"]
    ws = [str(e["stream"]) for p, e in transcribed if p.parent.name == "ws"]
    assert rest and all(route(label) is not None for label in rest)
    assert ws and all(ws_label(label) is not None for label in ws)


def _write(
    directory: Path,
    entries: Iterable[tuple[str, str, Any]],
    stream: str = "GET /v5/order/realtime",
) -> None:
    """A corpus directory: `(file, source, body)` per entry under `rest/`, one stream."""
    (directory / "rest").mkdir(parents=True)
    fixtures = []
    for name, source, body in entries:
        (directory / "rest" / name).write_text(json.dumps(body), encoding="utf-8")
        fixtures.append({"path": f"rest/{name}", "stream": stream, "source": source})
    (directory / "manifest.json").write_text(json.dumps({"fixtures": fixtures}), encoding="utf-8")


#: Loaded by name, as the fixtures README's replacement procedure greps for: the PR that
#: replaces this transcription repoints it.
REALTIME = rest("rest/trading-order-realtime.json")


def _recorded(**row: Any) -> dict[str, Any]:
    """A planted recording: the transcription with `row`'s fields changed (a test input)."""
    first = {**REALTIME["result"]["list"][0], **row}
    return {**REALTIME, "result": {**REALTIME["result"], "list": [first]}}


def test_a_recording_that_adds_drops_or_retypes_a_field_is_caught(tmp_path: Path) -> None:
    changed = _recorded(newVenueField="x", qty=0.1)
    del changed["result"]["list"][0]["smpGroup"]
    _write(tmp_path / "a", [("t.json", TRANSCRIBED, REALTIME)])
    _write(tmp_path / "b", [("r.json", "capture (redacted)", changed)])
    [found] = drift(tmp_path).values()
    assert "recorded only: result.list[].newVenueField" in found
    assert "transcribed only: result.list[].smpGroup" in found
    assert "retyped: result.list[].qty ['string'] -> ['number']" in found


def test_a_recording_that_agrees_or_shows_no_rows_passes(tmp_path: Path) -> None:
    empty = {**REALTIME, "result": {**REALTIME["result"], "list": []}}
    _write(
        tmp_path / "a",
        [
            ("t.json", TRANSCRIBED, REALTIME),
            ("same.json", "capture (redacted)", _recorded()),
            ("empty.json", "capture (redacted)", empty),
            ("built.json", "documented-shape (exception #1778 A)", {"other": 1}),
        ],
    )
    assert drift(tmp_path) == {}


def test_a_recording_of_another_return_code_is_another_shape(tmp_path: Path) -> None:
    error = {"retCode": 110001, "retMsg": "Order does not exist"}
    _write(tmp_path / "a", [("t.json", TRANSCRIBED, REALTIME), ("e.json", "capture", error)])
    assert drift(tmp_path) == {}


def test_a_recording_labelled_without_its_method_is_still_compared(tmp_path: Path) -> None:
    _write(tmp_path / "a", [("t.json", TRANSCRIBED, REALTIME)])
    _write(tmp_path / "b", [("r.json", "capture", _recorded(qty=0.1))], stream="/v5/order/realtime")
    [found] = drift(tmp_path).values()
    assert found == ["retyped: result.list[].qty ['string'] -> ['number']"]


def test_a_recording_of_another_method_on_the_route_is_another_shape(tmp_path: Path) -> None:
    _write(tmp_path / "a", [("t.json", TRANSCRIBED, REALTIME)])
    _write(tmp_path / "b", [("r.json", "capture", {"other": 1})], stream="POST /v5/order/realtime")
    assert drift(tmp_path) == {}


def test_a_recorded_error_is_compared_on_the_error_rows_keys_only(tmp_path: Path) -> None:
    """The error table shows a code and a text: a recording's envelope around them agrees, a
    text of another type does not."""
    row = {"retCode": 110072, "retMsg": "OrderLinkedID is duplicate"}
    envelope = row | {"result": {}, "retExtInfo": {}, "time": 1}
    _write(tmp_path / "a", [("t.json", TRANSCRIBED, row)], stream="POST /v5/order/create")
    _write(tmp_path / "b", [("r.json", "capture", envelope)], stream="POST /v5/order/create")
    assert drift(tmp_path) == {}
    _write(
        tmp_path / "c",
        [("r.json", "capture", envelope | {"retMsg": 7})],
        stream="POST /v5/order/create",
    )
    [found] = drift(tmp_path).values()
    assert found == ["retyped: retMsg ['string'] -> ['number']"]


def test_a_rest_recording_whose_label_names_no_route_is_reported(tmp_path: Path) -> None:
    _write(tmp_path / "a", [("r.json", "capture", REALTIME)], stream="order realtime page")
    assert unrouted(tmp_path) == ["a/rest/r.json"]
