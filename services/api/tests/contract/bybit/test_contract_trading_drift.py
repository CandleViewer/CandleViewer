"""Drift check of the docs-transcribed order-path shapes (G-8, #2877, ruling R2).

A transcription (`source: docs-transcribed` in a corpus manifest) stands in for a recording that
does not exist yet. The moment a recording of the same stream and return code lands (E29-K01,
#843, in any dated corpus directory), its field paths and JSON types must agree with the
transcription's, or this test fails naming them; the recording then replaces the transcription.
A field the recording cannot show (rows of an empty list) is not a disagreement.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tests._corpus import CORPUS_ROOT

TRANSCRIBED = "docs-transcribed"


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


def disagreements(transcribed: Any, recorded: Any) -> list[str]:
    """Where a recording differs from a transcription of its shape."""
    want, got = _paths(transcribed), _paths(recorded)
    out = [f"recorded only: {p}" for p in sorted(set(got) - set(want))]
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


def _shape_key(path: Path, entry: Mapping[str, Any]) -> tuple[str, object] | None:
    """The stream and return code a REST body answers; `None` for anything else."""
    if path.suffix != ".json":
        return None
    body = json.loads(path.read_text(encoding="utf-8"))
    code = body.get("retCode") if isinstance(body, dict) else None
    return str(entry["stream"]), code


def drift(root: Path) -> dict[str, list[str]]:
    """Per transcription, its disagreements with every recording of its shape."""
    entries = _entries(root)
    recordings: dict[tuple[str, object], list[Path]] = {}
    for path, entry in entries:
        source = str(entry.get("source", ""))
        if source != TRANSCRIBED and not source.startswith("documented-shape"):
            key = _shape_key(path, entry)
            if key is not None:
                recordings.setdefault(key, []).append(path)
    out: dict[str, list[str]] = {}
    for path, entry in entries:
        key = _shape_key(path, entry) if entry.get("source") == TRANSCRIBED else None
        for recorded in recordings.get(key, []) if key is not None else []:
            found = disagreements(_load(path), _load(recorded))
            if found:
                out[f"{path.name} vs {recorded.parent.name}/{recorded.name}"] = found
    return out


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_no_recording_disagrees_with_a_transcription() -> None:
    assert drift(CORPUS_ROOT) == {}


def _write(directory: Path, entries: Iterable[tuple[str, str, Any]]) -> None:
    """A corpus directory: `(file, source, body)` per entry, one stream."""
    directory.mkdir(parents=True)
    fixtures = []
    for name, source, body in entries:
        (directory / name).write_text(json.dumps(body), encoding="utf-8")
        fixtures.append({"path": name, "stream": "GET /v5/order/realtime", "source": source})
    (directory / "manifest.json").write_text(json.dumps({"fixtures": fixtures}), encoding="utf-8")


REALTIME = _load(CORPUS_ROOT / "2026-10-05" / "rest" / "trading-order-realtime.json")


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
