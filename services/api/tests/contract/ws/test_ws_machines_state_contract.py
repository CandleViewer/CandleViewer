"""E17-T08 contract slice: `machines.{entity}.state` (23-ws-protocol.md §6.4, §12.8, §15.10).

The publisher has not landed yet. These tests pin the contract by binding its sources together:
the §6.4 kind and RBAC tables, the §15.10 schema (bundled in docs/plan/ws-schema.json), the §16.6
open items, the role grants in auth/rbac_seed.json and the chart contracts in
candleviewer/statechart/machines (C-2.19). File reads only.
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
_SCHEMA: dict[str, Any] = _SCHEMAS["cv://ws/v1/machines.schema.json"]
_COMMON: dict[str, Any] = _SCHEMAS["cv://ws/v1/common.schema.json"]["$defs"]
_PAYLOAD = Draft202012Validator(_SCHEMA, registry=_REGISTRY)
_ENVELOPE = Draft202012Validator(_SCHEMAS["cv://ws/v1/envelope.schema.json"], registry=_REGISTRY)
_API = _ROOT / "services" / "api" / "candleviewer"
_GRANTS: dict[str, list[str]] = json.loads(
    (_API / "auth" / "rbac_seed.json").read_text(encoding="utf-8")
)["role_permissions"]
_MACHINES = _API / "statechart" / "machines"
#: chart id -> (catalogue number from the BNN file name, chart JSON)
_CHARTS: dict[str, tuple[int, dict[str, Any]]] = {
    chart["id"]: (int(path.name[1:3]), chart)
    for path in sorted(_MACHINES.glob("B*.json"))
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
KINDS = _table(_S64, "`{entity}`")  # B | entity | machine_kind | id format | scope | summary keys
RBAC = _table(_S64, "Kind")  # B | kind | read rule | owner | 3 actors | state
MACHINE_IDS = [m for row in KINDS for m in _codes(row[2])]
_PENDING = "`deny_pending_decision`"


def _kind(row: list[str]) -> str:
    return _codes(row[1])[0].split(":", 1)[0]


def _scope(row: list[str]) -> str:
    """The §6.4 scope column reduced to its class: account, user or none."""
    if "account" in row[4]:
        return "account"
    if "`user_id`" in row[4]:
        return "user"
    assert row[4] == "none", row
    return "none"


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
        for machine_id in _codes(row[2]):
            assert numbers[0] <= _CHARTS[machine_id][0] <= numbers[-1], (row[0], machine_id)
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


#: The scope each kind's registry entry carries (security review of #2438, D2 on #414).
_SCOPES = {
    "account": {"order", "trade_group", "leg", "algo", "reconciliation", "risk_lockout"},
    "user": {"alert", "replay", "session"},
    "none": {"recording", "book", "live_gate", "kill_switch"},
}


def test_scope_column_binds_each_kind_to_its_scope_class() -> None:
    assert {k: {_kind(r) for r in KINDS if _scope(r) == k} for k in _SCOPES} == _SCOPES


#: Rules the publisher must implement, pinned as text so they cannot quietly change (security
#: review of #2438, rounds 2 and 3). All are §6.4 sentences except the §15.10 one.
_RULES = {
    "scope_is_immutable": "Each registry entry carries the immutable scope in the column above.",
    "scope_bound": "builds the machine and again when it restores one.",
    "scope_missing_refused": "An entry of a scoped kind that has no scope is refused to every role",
    "scope_missing_counted": "The publisher counts and logs each such entry when it is published",
    "scope_missing_metric": "`cv_machine_ws_scope_missing_total{entity_kind}` counts each payload",
    "synchronous": "entry synchronously, never through an awaited lookup",
    "self_kinds_include_owner": "stays self-scoped for every role, Owner included",
    "role_change": "Every RBAC change (§9.5) re-applies the whole row",
    "audit_reason_column": "one internal reason, in the `reason` column only",
    "audit_fields_identical": "`outcome` and `severity` are identical for every reason",
    "audit_server_side": "The reason stays server-side; the client sees only the codes above.",
    "audit_no_tombstones": "so no tombstone of a removed entity is kept",
    "pending_woken": "until the first publish on its topic wakes it",
    "pending_never_retried": "subscription is never retried on inbound frames.",
    "no_lease": "never takes an upstream or bar lease and never triggers auto-record",
    "symbol_cap": "A `recording:` or `book:` entity counts toward the 40-symbol cap",
    "registry_bound": "it is bounded by the live interpreters it mirrors",
    "resubscribe_consistent": "`resubscribe_allowed` is `true` for an unscoped kind",
    "schema_closes_per_kind": "the schema below closes `context_summary` per `machine_kind`",
}


@pytest.mark.parametrize("rule", sorted(_RULES))
def test_rule_is_normative_text(rule: str) -> None:
    section = _section("### 15.10 ", "## 16. ") if rule == "schema_closes_per_kind" else _S64
    assert _RULES[rule] in section


def test_check_order_is_permission_then_role_then_registry() -> None:
    steps = ["1. **Permission.**", "2. **Role.**", "3. **Registry and scope.**"]
    assert sorted(steps, key=_S64.index) == steps


def test_unscoped_kinds_in_the_pending_rule_match_the_scope_column() -> None:
    unscoped = re.search(r"For an unscoped kind \(([^)]*)\), an entity with no entry is not", _S64)
    assert unscoped and set(_codes(unscoped.group(1))) == _SCOPES["none"]


_ACTORS = (  # RBAC matrix actors: the entity is on account A, held only by manager_with_grant
    ("owner", True),
    ("manager", True),
    ("manager", False),
    ("viewer", False),
)


def _expected(kind_row: list[str], rbac_row: list[str]) -> list[str]:
    """§6.4 check order: permission, then role (pending decision), then registry and scope."""
    perms = [c for c in _codes(rbac_row[2]) if re.fullmatch(r"[a-z_]+:[a-z_]+", c)]
    out = []
    for role, granted in _ACTORS:
        if perms and not ({"*", perms[0]} & set(_GRANTS[role])):
            out.append("forbidden")
        elif rbac_row[7].startswith(_PENDING) and role != "owner":
            out.append("forbidden")
        elif _scope(kind_row) == "account" and not granted:
            out.append("account_scope_denied")
        else:
            out.append("sub_ok")  # a user-scoped entity is the caller's own
    return out


def test_rbac_cells_follow_the_check_order_and_the_role_grants() -> None:
    assert [_codes(r[1])[0] for r in RBAC] == [_kind(r) for r in KINDS]
    for kind_row, row in zip(KINDS, RBAC, strict=True):
        cells = [_codes(c)[0] for c in row[3:7]]
        assert cells == _expected(kind_row, row), row


def test_the_ws_registry_kinds_are_the_6_4_tables() -> None:
    """The publisher's kind table (E17-T08): id format, read permission, scope and pending rule."""
    from candleviewer.ws.topics import MACHINE_KINDS

    scopes = {"account": "granted_accounts", "user": "self", "none": "none"}
    expected = {}
    for kind_row, row in zip(KINDS, RBAC, strict=True):
        perms = [c for c in _codes(row[2]) if re.fullmatch(r"[a-z_]+:[a-z_]+", c)] or [None]
        pending = row[7].startswith(_PENDING)
        expected[_kind(kind_row)] = (kind_row[3], perms[0], scopes[_scope(kind_row)], pending)
    assert {
        k: (m.id_format, m.permission and m.permission.value, m.scope.value, m.pending)
        for k, m in MACHINE_KINDS.items()
    } == expected


def test_deny_pending_decision_rows_cite_their_open_item() -> None:
    open_items = _section("### 16.6 ")
    for row in RBAC:
        if row[7].startswith(_PENDING):
            (item,) = re.findall(r"W\d+", row[7])
            assert f"| {item}  " in open_items and "machines.{entity}.state" in open_items
        else:
            assert row[7] == "executable", row


#: §6.4 redaction: never secrets, user ids, free text, `_fault`, `*_us`, ids, money, cross-account.
_NEVER = re.compile(
    r"^_|_us$|_ids?$|_by$|reason|error|token|secret|qty|price|pnl|equity|balance|loss|margin"
    r"|limit|notional|channel|^accounts_"
)


def test_context_summary_keys_are_declared_typed_and_closed_per_kind() -> None:
    table = {m: set(_codes(row[5])) for row in KINDS for m in _codes(row[2])}
    for machine_id, keys in table.items():
        assert keys <= set(_CHARTS[machine_id][1]["context"]), (machine_id, keys)
    union = set().union(*table.values())
    assert union == set(_SCHEMA["properties"]["context_summary"]["properties"])
    assert sorted(k for k in union if _NEVER.search(k)) == []
    per_kind, carriers = {}, set()
    for block in _SCHEMA["allOf"]:  # §15.10 closure must equal the §6.4 table exactly
        if "required" in block["if"]:
            carriers = set(block["then"]["properties"]["machine_kind"]["enum"])
            continue
        kind = block["if"]["properties"]["machine_kind"]["const"]
        summary = block["then"]["properties"]["context_summary"]
        per_kind[kind] = set(summary["propertyNames"]["enum"])
    assert per_kind == {m: keys for m, keys in table.items() if keys}
    assert carriers == set(per_kind)


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


def _lock_hash(machine_id: str) -> str:
    lock = json.loads((_MACHINES / "machine_hashes.lock").read_text(encoding="utf-8"))
    return str(lock["machines"][machine_id]["hash"])


def test_section_12_8_frames_validate_and_follow_the_order_chart() -> None:
    chart = _CHARTS["order"][1]
    _, regions = _published(chart)
    block = _section("### 12.8 ", "## 13. ")
    frames = [json.loads(line[4:]) for line in block.splitlines() if line.startswith("S→C ")]
    data = [f for f in frames if f["t"] in {"snap", "d"}]
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
        assert p["tags"] == sorted(tags) and p["machine_hash"] == _lock_hash("order")


_SYMBOL = _COMMON["symbol"]["pattern"].strip("^$")
_ID = {
    "uuid": "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    "symbol": _SYMBOL,
    "singleton": "",
}
_LONGEST = {"uuid": "ffffffff-ffff-4fff-8fff-ffffffffffff", "symbol": "A" * 20 + "USDT"}


def _grammar() -> re.Pattern[str]:
    alts = [re.escape(_kind(r)) + (f":{_ID[r[3]]}" if _ID[r[3]] else "") for r in KINDS]
    return re.compile(rf"^machines\.(?:{'|'.join(alts)})\.state$")


def test_entity_grammar_is_bounded_and_fits_the_envelope_topic_pattern() -> None:
    grammar, topic = _grammar(), re.compile(_COMMON["topic"]["pattern"])
    longest = 0
    for row in KINDS:
        ident = _LONGEST.get(row[3])
        ch = f"machines.{_kind(row)}{':' + ident if ident else ''}.state"
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
        "machines.book:BTCUSDT:50.state",  # the book tier is internal: one topic per symbol
        "machines.recording:btcusdt.state",  # not a §13 symbol
    ],
)
def test_entity_grammar_rejects(ch: str) -> None:
    assert _grammar().match(ch) is None


_REFUSED: list[tuple[str, str, dict[str, Any]]] = [
    ("24 §17.6 retired: entity_id", "order", {"entity_id": "0a000000-0000-4000-8000-0000000000aa"}),
    ("24 §17.6 retired: per-entity seq", "order", {"seq": 7}),
    ("24 §17.6 retired: state_ids", "order", {"state_ids": ["lifecycle.submitted"]}),
    ("24 §17.6 retired: published_enum", "order", {"published_enum": "submitted"}),
    ("a nested path is not a state", "order", {"state": "lifecycle.submitted"}),
    ("tags are identifiers", "order", {"tags": ["Protected"]}),
    ("machine_hash is sha256 hex", "order", {"machine_hash": "743dfaada4e3"}),
    ("environment is closed", "order", {"environment": "paper"}),
    ("one region is not parallel", "order", {"regions": {"lifecycle": "submitted"}}),
    ("user id (C-12.4)", "kill_switch", {"context_summary": {"engaged_by": "9f1c2b4e"}}),
    ("free text", "kill_switch", {"context_summary": {"reason": "manual halt"}}),
    ("exchange id", "order", {"context_summary": {"order_link_id": "cvl-3KtQ8fZ1nR0aB7cD2eF"}}),
    ("book of record", "order", {"context_summary": {"filled_qty": "0.2"}}),
    ("internal fault record", "order", {"context_summary": {"_fault": {"error": "boom"}}}),
    ("monotonic deadline", "order", {"context_summary": {"sl_deadline_us": 1}}),
    ("cross-account count", "kill_switch", {"context_summary": {"accounts_total": 5}}),
    ("typed key", "order", {"context_summary": {"halted_by_kill": "yes"}}),
    ("no empty summary", "order", {"context_summary": {}}),
    ("closed per kind", "order", {"context_summary": {"mfa_satisfied": True}}),
    ("a kind without keys", "risk_lockout", {"context_summary": {"scope": "global"}}),
]


@pytest.mark.parametrize(("why", "machine_id", "change"), _REFUSED, ids=[w for w, _, _ in _REFUSED])
def test_payload_refuses_fields_outside_the_contract(
    why: str, machine_id: str, change: dict[str, Any]
) -> None:
    assert list(_PAYLOAD.iter_errors(_payload(machine_id, **change))) != [], why


@pytest.mark.parametrize("missing", list(_SCHEMA["required"]))
def test_payload_requires(missing: str) -> None:
    payload = _payload("kill_switch")
    del payload[missing]
    assert list(_PAYLOAD.iter_errors(payload)) != []
