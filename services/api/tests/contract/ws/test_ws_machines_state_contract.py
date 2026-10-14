"""E17-T08 contract slice: `machines.{entity}.state` (23-ws-protocol.md §6.4, §12.8, §15.10).

The publisher has not landed yet. These tests pin the contract by binding its sources together:
the §6.4 kind and RBAC tables, the §15.10 schema (bundled in docs/plan/ws-schema.json), the §16.6
open items and the chart contracts in candleviewer/statechart/machines (C-2.19). File reads only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

_ROOT = Path(__file__).resolve().parents[5]
_DOC = (_ROOT / "docs" / "plan" / "23-ws-protocol.md").read_text(encoding="utf-8")
_BUNDLE: dict[str, Any] = json.loads(
    (_ROOT / "docs" / "plan" / "ws-schema.json").read_text(encoding="utf-8")
)
_SCHEMAS: dict[str, Any] = _BUNDLE["schemas"]
_REGISTRY: Registry[Any] = Registry().with_resources(
    (sid, Resource.from_contents(body)) for sid, body in _SCHEMAS.items()
)
_SCHEMA_ID = "cv://ws/v1/machines.schema.json"
_SCHEMA: dict[str, Any] = _SCHEMAS[_SCHEMA_ID]
_COMMON: dict[str, Any] = _SCHEMAS["cv://ws/v1/common.schema.json"]["$defs"]
_PAYLOAD = Draft202012Validator(_SCHEMA, registry=_REGISTRY)
_ENVELOPE = Draft202012Validator(_SCHEMAS["cv://ws/v1/envelope.schema.json"], registry=_REGISTRY)

_CHART_FILES = sorted((_ROOT / "services/api/candleviewer/statechart/machines").glob("B*.json"))
#: chart id -> (catalogue number from the BNN file name, chart JSON)
_CHARTS: dict[str, tuple[int, dict[str, Any]]] = {
    chart["id"]: (int(path.name[1:3]), chart)
    for path in _CHART_FILES
    for chart in [json.loads(path.read_text(encoding="utf-8"))]
}


def _section(start: str, end: str | None = None) -> str:
    begin = _DOC.index(start)
    return _DOC[begin : _DOC.index(end, begin)] if end else _DOC[begin:]


def _table(text: str, second_header: str) -> list[list[str]]:
    """Body rows of the table whose second header cell is `second_header`."""
    lines = text.splitlines()
    for n, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) > 1 and cells[1] == second_header:
            body = []
            for row in lines[n + 2 :]:
                if not row.startswith("|"):
                    break
                body.append([c.strip() for c in row.strip().strip("|").split("|")])
            return body
    raise AssertionError(f"no table with header {second_header!r}")


def _codes(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


_S64 = _section("### 6.4 ", "## 7. ")
KINDS = _table(_S64, "`{entity}`")  # B | entity | machine_kind | id format | summary keys
RBAC = _table(_S64, "Kind")  # B | kind | read rule | owner | 3 actors | state
MACHINE_IDS = [m for row in KINDS for m in _codes(row[2])]


def _kind(row: list[str]) -> str:
    return _codes(row[1])[0].split(":", 1)[0]


def _published(chart: dict[str, Any]) -> tuple[set[str], dict[str, set[str]]]:
    """§6.4: `state` is a direct child of the root, or of the first region of a parallel chart."""
    states: dict[str, Any] = chart["states"]
    if chart.get("type") != "parallel":
        return set(states), {}
    regions = {name: set(node["states"]) for name, node in states.items()}
    return regions[next(iter(states))], regions


def _all_tags(node: dict[str, Any]) -> set[str]:
    out = set(node.get("tags", []))
    for child in (node.get("states") or {}).values():
        out |= _all_tags(child)
    return out


def _payload(machine_id: str, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "machine_kind": machine_id,
        "state": sorted(_published(_CHARTS[machine_id][1])[0])[0],
        "tags": [],
        "degraded": False,
        "machine_hash": "0" * 64,
        "environment": "demo",
        "updated_at_ms": 1789134000000,
    }
    return {**base, **fields}


def test_topic_is_catalogued_with_its_payload_schema() -> None:
    entry = {"topicPattern": "machines.{entity}.state", "payloadSchema": "MachineStateUpdate"}
    assert entry in _BUNDLE["topicCatalogue"]
    assert _SCHEMA["title"] == "machines.{entity}.state"


def test_kind_table_matches_the_schema_and_the_catalogue_charts() -> None:
    assert MACHINE_IDS == _SCHEMA["properties"]["machine_kind"]["enum"]
    assert len(set(MACHINE_IDS)) == len(MACHINE_IDS) == 16
    kinds = [_kind(row) for row in KINDS]
    assert len(set(kinds)) == len(kinds) == 13
    for row in KINDS:
        numbers = [int(n) for n in re.findall(r"\d+", row[0])]
        low, high = numbers[0], numbers[-1]
        for machine_id in _codes(row[2]):
            assert low <= _CHARTS[machine_id][0] <= high, (row[0], machine_id)
    # 28 §1.1: B1-B20, all present; the four without a public id are W9 in §16.6.
    unexposed = {"position_protection", "rule_instance", "ws_conn", "paper_account"}
    assert set(_CHARTS) == set(MACHINE_IDS) | unexposed
    assert all(f"`{m}`" in _section("| W9 ") for m in unexposed)


def test_parallel_charts_and_first_regions_are_the_ones_6_4_names() -> None:
    parallel = {
        m: next(iter(_CHARTS[m][1]["states"]))
        for m in MACHINE_IDS
        if _CHARTS[m][1].get("type") == "parallel"
    }
    assert parallel == {"order": "lifecycle", "session": "auth"}
    assert "(`lifecycle`, `auth`)" in _S64


#: §6.4 redaction: never secrets, user ids, free text, `_fault`, `*_us`, ids, money, cross-account.
_NEVER = re.compile(r"^_|_us$|_ids?$|_by$|reason|error|token|secret|qty|price|pnl|equity|balance")


def test_context_summary_keys_are_typed_and_declared_by_their_chart() -> None:
    union: set[str] = set()
    for row in KINDS:
        keys = set(_codes(row[4]))
        for machine_id in _codes(row[2]):
            assert keys <= set(_CHARTS[machine_id][1]["context"]), (machine_id, keys)
        union |= keys
    assert union == set(_SCHEMA["properties"]["context_summary"]["properties"])
    assert sorted(k for k in union if _NEVER.search(k) or k.startswith("accounts_")) == []
    assert _SCHEMA["properties"]["context_summary"]["additionalProperties"] is False


@pytest.mark.parametrize("machine_id", MACHINE_IDS)
def test_every_chart_identifier_fits_the_payload(machine_id: str) -> None:
    chart = _CHARTS[machine_id][1]
    values, regions = _published(chart)
    for state in sorted(values):
        active = {r: sorted(v)[0] for r, v in regions.items()} or None
        payload = _payload(machine_id, state=state, tags=sorted(_all_tags(chart)))
        if active is not None:
            payload["regions"] = {**active, next(iter(regions)): state}
        assert list(_PAYLOAD.iter_errors(payload)) == [], (machine_id, state)


def _frames_12_8() -> list[dict[str, Any]]:
    block = _section("### 12.8 ", "## 13. ")
    return [json.loads(line[4:]) for line in block.splitlines() if line.startswith("S→C ")]


def test_section_12_8_frames_validate_and_follow_the_order_chart() -> None:
    chart = _CHARTS["order"][1]
    _, regions = _published(chart)
    data = [f for f in _frames_12_8() if f["t"] in {"snap", "d"}]
    assert [f["t"] for f in data] == ["snap", "d"] and data[1]["s"] == data[0]["s"] + 1
    for frame in data:
        assert list(_ENVELOPE.iter_errors(frame)) == []
        p = frame["p"]
        assert list(_PAYLOAD.iter_errors(p)) == []
        assert p["state"] == p["regions"]["lifecycle"] and set(p["regions"]) == set(regions)
        assert all(state in regions[r] for r, state in p["regions"].items())
        tags = {
            t
            for r, s in p["regions"].items()
            for t in chart["states"][r]["states"][s].get("tags", [])
        }
        assert p["tags"] == sorted(tags)
        assert p["machine_hash"] == _lock_hash("order")


def _lock_hash(machine_id: str) -> str:
    lock = _ROOT / "services/api/candleviewer/statechart/machines/machine_hashes.lock"
    return str(json.loads(lock.read_text(encoding="utf-8"))["machines"][machine_id]["hash"])


_ID = {
    "uuid": "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    "symbol": _COMMON["symbol"]["pattern"].strip("^$"),
    "symbol, depth": _COMMON["symbol"]["pattern"].strip("^$") + ":(?:1|50|200|500)",
    "singleton": "",
}
_LONGEST = {
    "uuid": "ffffffff-ffff-4fff-8fff-ffffffffffff",
    "symbol": "ABCDEFGHIJKLMNOPQRSTUSDT",
    "symbol, depth": "ABCDEFGHIJKLMNOPQRSTUSDT:500",
    "singleton": "",
}


def _grammar() -> re.Pattern[str]:
    alts = [re.escape(_kind(r)) + (f":{_ID[r[3]]}" if _ID[r[3]] else "") for r in KINDS]
    return re.compile(rf"^machines\.(?:{'|'.join(alts)})\.state$")


def test_entity_grammar_is_bounded_and_fits_the_envelope_topic_pattern() -> None:
    grammar, topic = _grammar(), re.compile(_COMMON["topic"]["pattern"])
    longest = 0
    for row in KINDS:
        entity = _kind(row) + (f":{_LONGEST[row[3]]}" if _LONGEST[row[3]] else "")
        ch = f"machines.{entity}.state"
        assert grammar.match(ch) and topic.match(ch), ch
        longest = max(longest, len(ch))
    assert longest == 66 <= _COMMON["topic"]["maxLength"] and "has 66 characters" in _S64
    examples = re.findall(r'"ch":"(machines\.[^"]+)"', _section("### 12.8 ", "## 13. "))
    assert examples and all(grammar.match(ch) for ch in examples)


@pytest.mark.parametrize(
    "ch",
    [
        "machines.order:0A000000-0000-4000-8000-000000000001.state",  # one spelling per entity
        "machines.position_protection:a1000000-0000-4000-8000-000000000001.state",  # W9
        "machines.kill_switch:a1000000-0000-4000-8000-000000000001.state",  # singleton with id
        "machines.order.state",  # id missing
        "machines.book:BTCUSDT:25.state",  # depth not in {1, 50, 200, 500}
        "machines.recording:btcusdt.state",  # not a §13 symbol
    ],
)
def test_entity_grammar_rejects(ch: str) -> None:
    assert _grammar().match(ch) is None


_OUTCOMES = {"sub_ok", "forbidden", "account_scope_denied"}


def test_rbac_table_uses_the_matrix_vocabulary_and_cites_open_items() -> None:
    assert [_codes(r[1])[0] for r in RBAC] == [_kind(r) for r in KINDS]
    open_items = _section("### 16.6 ")
    for row in RBAC:
        cells = [_codes(c)[0] for c in row[3:7]]
        assert set(cells) <= _OUTCOMES and cells[0] == "sub_ok", row
        if row[7].startswith("`not_executable`"):
            (item,) = re.findall(r"W\d+", row[7])
            assert cells[1:] == ["forbidden"] * 3, row  # deny by default until decided
            assert f"| {item}  " in open_items and "machines.{entity}.state" in open_items
        else:
            assert row[7] == "executable", row


_REFUSED: list[tuple[str, dict[str, Any]]] = [
    ("24 §17.6 retired: entity_id", {"entity_id": "0a000000-0000-4000-8000-000000000001"}),
    ("24 §17.6 retired: per-entity seq", {"seq": 7}),
    ("24 §17.6 retired: state_ids", {"state_ids": ["lifecycle.submitted"]}),
    ("24 §17.6 retired: published_enum", {"published_enum": "submitted"}),
    ("a nested path is not a state", {"state": "lifecycle.submitted"}),
    ("tags are identifiers", {"tags": ["Protected"]}),
    ("machine_hash is sha256 hex", {"machine_hash": "743dfaada4e3"}),
    ("environment is closed", {"environment": "paper"}),
    ("one region is not parallel", {"regions": {"lifecycle": "submitted"}}),
    ("user id (C-12.4)", {"context_summary": {"engaged_by": "9f1c2b4e"}}),
    ("free text", {"context_summary": {"reason": "manual halt"}}),
    ("exchange id", {"context_summary": {"order_link_id": "cvl-3KtQ8fZ1nR0aB7cD2eF9g-1a2B-0Ten"}}),
    ("book of record", {"context_summary": {"filled_qty": "0.2"}}),
    ("internal fault record", {"context_summary": {"_fault": {"error": "boom"}}}),
    ("monotonic deadline", {"context_summary": {"sl_deadline_us": 1}}),
    ("cross-account count", {"context_summary": {"accounts_total": 5}}),
    ("typed key", {"context_summary": {"halted_by_kill": "yes"}}),
    ("no empty summary", {"context_summary": {}}),
]


@pytest.mark.parametrize(("why", "change"), _REFUSED, ids=[w for w, _ in _REFUSED])
def test_payload_refuses_fields_outside_the_contract(why: str, change: dict[str, Any]) -> None:
    assert list(_PAYLOAD.iter_errors(_payload("order", **change))) != [], why


@pytest.mark.parametrize("missing", list(_SCHEMA["required"]))
def test_payload_requires(missing: str) -> None:
    payload = _payload("kill_switch")
    del payload[missing]
    assert list(_PAYLOAD.iter_errors(payload)) != []
