"""Drift check of the docs-transcribed order-path shapes (G-8, #2877, ruling R2).

A transcription (`source: docs-transcribed` in a corpus manifest) stands in for a recording that
does not exist yet. The moment a recording of the same route and return code lands (E29-K01,
#843, in any dated corpus directory), its field paths and JSON types must agree with the
transcription's, or this test fails naming them; the recording then replaces the transcription.
The route is read from the manifest's `stream` label, `<METHOD> /v5/<path>` (a label without the
method matches on the path), so a recording labelled another way is still compared, and a REST
recording whose label names no route fails here rather than going unchecked. A field the
recording cannot show (rows of an empty list) is not a disagreement, and an error-row
transcription, which holds only the error table's code and text, is compared on those keys only.
"""

from __future__ import annotations

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


def test_no_recording_disagrees_with_a_transcription() -> None:
    assert drift(CORPUS_ROOT) == {}


def test_every_rest_recording_names_its_route() -> None:
    assert unrouted(CORPUS_ROOT) == []


def test_every_transcription_names_its_route() -> None:
    labels = [
        str(entry["stream"])
        for _, entry in _entries(CORPUS_ROOT)
        if entry.get("source") == TRANSCRIBED
    ]
    assert labels and all(route(label) is not None for label in labels)


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
