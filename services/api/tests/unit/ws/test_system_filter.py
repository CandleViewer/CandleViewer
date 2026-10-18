"""SR-188 (#2175): `system_view`, each role's view of a `system` frame (`23-ws-protocol.md` §15.9).

Pure: no socket, no clock. Every expected body is written out here, never derived from the
module's tables, so a widened table fails a test. The tables are compared with the contract: the
schema of §15.9, and the prose table and sentence that say who receives what of it."""

from __future__ import annotations

import copy
import json
import re
import uuid
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws import system_filter
from candleviewer.ws.system_filter import (
    NEUTRAL_APPLIED,
    NEUTRAL_COMPONENT,
    NEUTRAL_EXCHANGE,
    NEUTRAL_FIELDS,
    NEUTRAL_KILL_SWITCH,
    kill_switch_view,
    system_view,
    withheld_reason,
)
from tests.unit.ws._seq_support import validate

ACC_A = uuid.UUID("0a000000-0000-4000-8000-00000000000a")
ACC_B = uuid.UUID("0a000000-0000-4000-8000-00000000000b")
ENGAGER = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001"
_BUNDLE = Path(__file__).resolve().parents[5] / "docs" / "plan" / "ws-schema.json"
_DOC = _BUNDLE.with_name("23-ws-protocol.md")
_SCHEMAS = json.loads(_BUNDLE.read_text(encoding="utf-8"))["schemas"]
_SCHEMA = _SCHEMAS["cv://ws/v1/system.schema.json"]


def principal(*roles: str, grants: tuple[AccountGrant, ...] = ()) -> PrincipalSnapshot:
    return PrincipalSnapshot(uuid.UUID(int=0x2175), frozenset(roles), frozenset(), grants)


OWNER = principal("owner")
MANAGER = principal("manager", grants=(AccountGrant(ACC_A, True, True, False),))
VIEWER = principal("viewer", grants=(AccountGrant(ACC_A, True, False, False),))
DENY_ALL = principal()  # a failed principal load, and every socket on the fake backend


def _same(body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return body, body  # role-neutral as emitted: every role gets this very object


_PART = {"name": "bybit_rest", "state": "degraded", "last_good_at": "2026-10-17T03:00:00Z"}
_EXCHANGE = {"public_ws": "connected", "private_ws": "resyncing", "rest": "degraded"}
_APPLIED = {
    "throttle_multiplier": 4,
    "forced_coalesce": True,
    "degraded_topics": ["heatmap.BTCUSDT"],
}
#: Fields no role-neutral list has: `rate_budget_free_pct` is the Owner's until E42-T05 decides.
_FOREIGN = {"account_id": "acct-b", "uid": "1234", "rate_budget_free_pct": 41.5}
_HEALTH = {
    "kind": "health",
    "health": "degraded",
    "clock_offset_ms": 4,
    "degraded_topics": [],
    "exchange": _EXCHANGE,
}
_HALT = {"kind": "kill_switch", "severity": "critical", "message": "Trading halted."}
_STATE = {"engaged": True, "scope": "accounts", "engaged_at_ms": 1789133000000}
_WHO = {"engaged_by": ENGAGER, "engaged_by_username": "owner.alice", "reason": "B breached its cap"}
_BOTH = {"exchange_account_ids": [str(ACC_A), str(ACC_B)]}

#: kind -> (the frame as emitted, what a Manager or Viewer viewing account A gets; None: nothing).
SAMPLES: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] = {
    "health": (
        _HEALTH
        | {"components": [_PART | {"detail": "acct 1"}], "feature_flags": {"a.b": True}}
        | {"kill_switch": {"engaged": True, "scope": "global", "engaged_by": ENGAGER}},
        _HEALTH | {"components": [_PART], "kill_switch": {"engaged": True, "scope": "global"}},
    ),
    "kill_switch": (
        _HALT | {"kill_switch": _STATE | _WHO | _BOTH, "actions": {"orders_cancelled": 7}},
        _HALT | {"kill_switch": _STATE | {"exchange_account_ids": [str(ACC_A)]}},
    ),
    "feature_flags": (
        {"kind": "feature_flags", "feature_flags": {"storage.cold_tier": False}},
        None,
    ),
    "exchange_state": _same(
        {"kind": "exchange_state", "public_ws": "resyncing", "exchange": _EXCHANGE}
    ),
    "connection_quality": _same(
        {"kind": "connection_quality", "class": "lagging", "rtt_ms": 200, "applied": _APPLIED}
    ),
    "shutdown_notice": _same(
        {"kind": "shutdown_notice", "reason": "deploy", "closing_in_ms": 5000}
    ),
    "degraded_data": _same({"kind": "degraded_data", "affected_symbols": ["BTCUSDT"]}),
    "clock_drift": _same({"kind": "clock_drift", "severity": "warning", "clock_offset_ms": 900}),
    "notice": _same({"kind": "notice", "severity": "critical", "reason": "net.binding_safe"}),
}


def _frame(body: Any) -> dict[str, Any]:
    return {"t": "d", "ch": "system", "s": 1, "ts": 1, "e": "j", "p": body}


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_owner_receives_every_contract_kind_whole(kind: str) -> None:
    body, _ = SAMPLES[kind]
    assert system_view(body, OWNER) is body
    validate(_frame(body))


@pytest.mark.parametrize("who", [MANAGER, VIEWER], ids=["manager", "viewer"])
@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_manager_and_viewer_receive_only_the_role_neutral_fields(
    kind: str, who: PrincipalSnapshot
) -> None:
    body, neutral = SAMPLES[kind]
    view = system_view(body, who)
    assert view == neutral
    if neutral is body:
        assert view is body  # nothing to leave out: passed on as is, never copied
    if view is not None:
        validate(_frame(view))


@pytest.mark.parametrize(
    ("grants", "ids", "kept"),
    [
        ((), [str(ACC_A), str(ACC_B)], []),  # no grant: the state still arrives, no account
        ((AccountGrant(ACC_A, False, True, False),), [str(ACC_A)], []),  # no view grant
        ((AccountGrant(ACC_A, True, False, True),), [str(ACC_A)], [str(ACC_A)]),  # frozen
        ((AccountGrant(ACC_A, True, False, False),), [str(ACC_A).upper(), ACC_A], [str(ACC_A)] * 2),
        ((AccountGrant(ACC_A, True, False, False),), ["no", 7, None, [str(ACC_A)]], []),
        ((AccountGrant(ACC_A, True, False, False),), str(ACC_A), []),  # not a list
    ],
    ids=["no-grant", "no-view", "frozen", "canonical", "malformed", "not-a-list"],
)
def test_kill_switch_accounts_are_cut_to_the_connections_account_scope(
    grants: tuple[AccountGrant, ...], ids: Any, kept: list[str]
) -> None:
    state = {"engaged": True, "scope": "accounts", "exchange_account_ids": ids}
    view = system_view(
        {"kind": "kill_switch", "kill_switch": state}, principal("viewer", grants=grants)
    )
    assert view == {"kind": "kill_switch", "kill_switch": state | {"exchange_account_ids": kept}}


_FALSY: tuple[Any, ...] = (None, "", 0, {}, ())  # not lists, so `[]`: never passed on as is


@pytest.mark.parametrize(
    ("ids", "kept"),
    [
        ((str(ACC_A), str(ACC_B), "x"), [str(ACC_A)]),  # a tuple is a list of ids
        (str(ACC_A).encode(), []),  # bytes are not
        *((empty, []) for empty in _FALSY),
    ],
)
def test_kill_switch_accounts_of_another_shape_are_a_tuple_cut_or_none(
    ids: Any, kept: list[str]
) -> None:
    state = {"engaged": True, "scope": "accounts", "exchange_account_ids": ids}
    view = system_view({"kind": "kill_switch", "kill_switch": state}, VIEWER)
    assert view == {"kind": "kill_switch", "kill_switch": state | {"exchange_account_ids": kept}}


@pytest.mark.parametrize("who", [OWNER, MANAGER, VIEWER, DENY_ALL])
def test_kill_switch_view_equals_the_system_frames_kill_switch(who: PrincipalSnapshot) -> None:
    state = SAMPLES["kill_switch"][0]["kill_switch"]  # what `auth_ok` carries is the same cut
    frame = system_view({"kind": "kill_switch", "kill_switch": state}, who)
    assert kill_switch_view(state, who) == (None if frame is None else frame["kill_switch"])


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "kill_switch"},
        {"kind": "kill_switch", "kill_switch": None},
        {"kind": "kill_switch", "kill_switch": "engaged", "severity": "critical"},
    ],
    ids=["missing", "null", "not-an-object"],
)
def test_a_kill_switch_frame_without_its_state_reaches_only_the_owner(body: dict[str, Any]) -> None:
    assert system_view(body, OWNER) is body
    assert system_view(body, MANAGER) is None and system_view(body, VIEWER) is None


def test_a_health_frame_drops_a_kill_switch_that_is_not_an_object() -> None:
    body = {"kind": "health", "health": "healthy", "kill_switch": ["engaged"]}
    assert system_view(body, VIEWER) == {"kind": "health", "health": "healthy"}


_OBJECTS: dict[str, dict[str, Any]] = {"exchange": _EXCHANGE, "applied": _APPLIED}
_NESTED = pytest.mark.parametrize(
    ("kind", "nested"),
    [("health", "exchange"), ("exchange_state", "exchange"), ("connection_quality", "applied")],
)


@pytest.mark.parametrize("who", [MANAGER, VIEWER], ids=["manager", "viewer"])
@_NESTED
def test_a_nested_object_reaches_a_manager_or_viewer_with_only_its_neutral_fields(
    kind: str, nested: str, who: PrincipalSnapshot
) -> None:
    body = {"kind": kind, nested: _OBJECTS[nested] | _FOREIGN}
    assert system_view(body, who) == {"kind": kind, nested: _OBJECTS[nested]}


@_NESTED
def test_a_nested_object_reaches_the_owner_whole(kind: str, nested: str) -> None:
    body = {"kind": kind, nested: _OBJECTS[nested] | _FOREIGN}
    assert system_view(body, OWNER) is body


@pytest.mark.parametrize(
    "junk", ["connected", ["public_ws"], 7, None], ids=["str", "list", "int", "none"]
)
@_NESTED
def test_a_nested_object_that_is_not_an_object_is_left_out(
    kind: str, nested: str, junk: Any
) -> None:
    assert system_view({"kind": kind, nested: junk}, VIEWER) == {"kind": kind}


@pytest.mark.parametrize(
    "parts", [(_PART | {"detail": "acct 1"},), (_PART,)], ids=["cut", "neutral"]
)
def test_a_tuple_of_components_reaches_a_viewer_as_a_list(
    parts: tuple[dict[str, str], ...],
) -> None:
    body = {"kind": "health", "components": parts}
    assert system_view(body, VIEWER) == {"kind": "health", "components": [_PART]}


@pytest.mark.parametrize("junk", ["bybit_rest", b"bybit_rest", _PART], ids=["str", "bytes", "dict"])
def test_components_that_are_not_a_list_or_tuple_are_left_out(junk: Any) -> None:
    assert system_view({"kind": "health", "components": junk}, VIEWER) == {"kind": "health"}


@pytest.mark.parametrize("who", [OWNER, MANAGER, VIEWER, DENY_ALL, None])
@pytest.mark.parametrize(
    "body",
    [
        *({"kind": kind} for kind in ("tick", "Notice", "", None, 7, ["notice"])),
        {"message": "no kind"},
        ["notice"],
        "notice",
        None,
    ],
)
def test_an_unknown_kind_or_a_non_object_reaches_nobody(
    body: Any, who: PrincipalSnapshot | None
) -> None:
    assert system_view(body, who) is None


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_a_connection_with_no_principal_or_no_role_gets_nothing(kind: str) -> None:
    body, _ = SAMPLES[kind]
    assert system_view(body, None) is None
    assert system_view(body, DENY_ALL) is None


def test_a_view_never_changes_the_frame_the_owner_still_gets_whole() -> None:
    body, neutral = SAMPLES["kill_switch"]
    before = copy.deepcopy(body)
    assert system_view(body, MANAGER) == neutral
    assert body == before
    assert system_view(body, OWNER) is body


def test_the_kind_table_is_the_contract_enum_and_names_only_schema_fields() -> None:
    """A `kind` added to §15.9 fails here until someone decides who may see it."""
    assert set(NEUTRAL_FIELDS) == set(_SCHEMA["properties"]["kind"]["enum"])
    assert all(fields <= set(_SCHEMA["properties"]) for fields in NEUTRAL_FIELDS.values())
    assert NEUTRAL_KILL_SWITCH < set(_SCHEMA["$defs"]["killSwitch"]["properties"])
    assert NEUTRAL_COMPONENT < set(_SCHEMA["properties"]["components"]["items"]["properties"])
    assert NEUTRAL_EXCHANGE <= set(_SCHEMA["properties"]["exchange"]["properties"])
    assert NEUTRAL_APPLIED <= set(_SCHEMA["properties"]["applied"]["properties"])


def _holds_objects(prop: dict[str, Any], where: str = "this property") -> bool:
    """Whether a schema property is, or may hold, an object: `type` `object`, or `array` of
    objects, alone or in a `type` list; a `$ref` to one; a `oneOf`, `anyOf` or `allOf` with one
    among its parts; an `enum` or `const` with a dict or list for a member. A shape it cannot
    classify, or a `type` that JSON Schema has not, raises and names `where`: none is skipped."""
    seen: list[bool] = []
    if "$ref" in prop:
        uri, _, pointer = prop["$ref"].partition("#")
        target: Any = _SCHEMAS[uri] if uri else _SCHEMA
        for part in pointer.strip("/").split("/"):
            target = target[part]
        seen.append(_holds_objects(target, where))
    for combinator in ("oneOf", "anyOf", "allOf"):
        seen += [_holds_objects(part, where) for part in prop.get(combinator, ())]
    if "type" in prop:
        kinds = prop["type"] if isinstance(prop["type"], list) else [prop["type"]]
        if not set(kinds) <= {"object", "array", "string", "number", "integer", "boolean", "null"}:
            raise AssertionError(f"cannot classify {prop!r} at {where}: no such type")
        items = prop.get("items", {})
        seen.append("object" in kinds or ("array" in kinds and _holds_objects(items, where)))
    if "enum" in prop or "const" in prop:
        members = [*prop.get("enum", ()), prop.get("const")]
        seen.append(any(isinstance(member, dict | list) for member in members))
    if not seen:
        raise AssertionError(f"cannot classify {prop!r} at {where}: teach it to `_holds_objects`")
    return any(seen)


_OBJECT_FIELDS = sorted(
    (kind, field)
    for kind, fields in NEUTRAL_FIELDS.items()
    for field in fields
    if _holds_objects(_SCHEMA["properties"][field], f"{kind}.{field}")
)


def test_the_probe_reaches_the_five_object_fields_that_have_an_allow_list() -> None:
    """`feature_flags` is cut by each key's registry `visibility` (E42-T03), the others by a set."""
    probed = {field for _, field in _OBJECT_FIELDS}
    assert probed >= {"kill_switch", "components", "exchange", "applied", "feature_flags"}


_OBJECTS_SPELLED = {
    "oneOf-ref-null": {"oneOf": [{"$ref": "#/$defs/killSwitch"}, {"type": "null"}]},
    "anyOf": {"anyOf": [{"type": "null"}, {"type": "object"}]},
    "allOf": {"allOf": [{"$ref": "#/$defs/killSwitch"}]},
    "type-list": {"type": ["object", "null"]},
    "array-in-type-list": {"type": ["array", "null"], "items": {"type": "object"}},
    "object-or-array-without-items": {"type": ["object", "array"]},
    "enum-with-an-object": {"enum": ["a", {"x": 1}]},
    "const-object": {"const": {"x": 1}},
}
_SCALARS_SPELLED = {
    "oneOf": {"oneOf": [{"type": "string"}, {"type": "null"}]},
    "anyOf-enum": {"anyOf": [{"enum": ["a"]}, {"type": "integer"}]},
    "type-list": {"type": ["string", "number", "integer", "boolean", "null"]},
    "array-in-type-list": {"type": ["array", "null"], "items": {"type": "string"}},
    "enum": {"enum": ["a", "b"]},
    "const": {"const": 1},
}
_NOT_UNDERSTOOD = {
    "any": {},
    "not": {"not": {"type": "object"}},
    "array-without-items": {"type": "array"},
    "part-of-oneOf": {"oneOf": [{"type": "null"}, {"minimum": 1}]},
    "unknown-type": {"type": "any"},
    "unknown-type-in-a-list": {"type": ["object", "frob"]},
}


@pytest.mark.parametrize("spelling", _OBJECTS_SPELLED.values(), ids=list(_OBJECTS_SPELLED))
def test_the_probe_lists_a_property_however_an_object_is_spelled(spelling: dict[str, Any]) -> None:
    """A nullable object (`oneOf [$ref, null]`, `anyOf`, `allOf`, `type [object, null]`) is one."""
    assert _holds_objects(spelling)


@pytest.mark.parametrize("spelling", _SCALARS_SPELLED.values(), ids=list(_SCALARS_SPELLED))
def test_the_probe_lists_no_property_that_cannot_hold_an_object(spelling: dict[str, Any]) -> None:
    assert not _holds_objects(spelling)


@pytest.mark.parametrize("shape", _NOT_UNDERSTOOD.values(), ids=list(_NOT_UNDERSTOOD))
def test_the_probe_fails_on_a_shape_it_cannot_classify(shape: dict[str, Any]) -> None:
    with pytest.raises(AssertionError, match=r"cannot classify .* at kind\.field"):
        _holds_objects(shape, "kind.field")


@pytest.mark.parametrize(
    ("kind", "field"), _OBJECT_FIELDS, ids=[f"{k}.{f}" for k, f in _OBJECT_FIELDS]
)
def test_an_object_field_of_a_neutral_list_reaches_a_viewer_cut_to_an_allow_list(
    kind: str, field: str
) -> None:
    """An object-typed property that joins a list without a nested allow-list passes whole."""
    for probe in ({"zz_probe": 1}, [{"zz_probe": 1}]):
        view = system_view({"kind": kind, field: probe}, VIEWER)
        assert "zz_probe" not in json.dumps(view), f"`{kind}.{field}` reaches a Viewer whole"


def test_no_table_of_the_filter_can_be_widened_at_run_time() -> None:
    tables = {name: value for name, value in vars(system_filter).items() if name[:2] != "__"}
    assert [name for name, value in tables.items() if isinstance(value, dict | set | list)] == []
    assert isinstance(NEUTRAL_FIELDS, MappingProxyType)
    assert all(isinstance(fields, frozenset) for fields in NEUTRAL_FIELDS.values())


def _section_15_9() -> str:
    text = _DOC.read_text(encoding="utf-8")
    return text[text.index("### 15.9 `SystemUpdate`") : text.index("### 15.10")]


def _rows() -> dict[str, str]:
    """kind -> the cell of the §15.9 table that lists what a Manager or Viewer also receives."""
    rows = re.findall(r"^\| `(\w+)` +\| (.+?) +\|$", _section_15_9(), flags=re.MULTILINE)
    assert len({kind for kind, _ in rows}) == len(rows), "a kind has two rows in the §15.9 table"
    return {kind: cell for kind, cell in rows if kind != "kind"}  # `kind`: the header row


def _fields(cell: str) -> set[str]:
    """The fields a table cell lists for the frame itself: its code spans outside parentheses
    and outside a `with only` list (the fields of a nested object). `none` lists no field."""
    if cell.startswith("none"):
        return set()
    return set(re.findall(r"`(\w+)`", re.sub(r"\([^()]*\)", "", cell).split(" with only ")[0]))


def test_the_section_15_9_table_has_a_row_for_each_contract_kind_and_no_other() -> None:
    assert sorted(_rows()) == sorted(_SCHEMA["properties"]["kind"]["enum"])


@pytest.mark.parametrize("kind", sorted(NEUTRAL_FIELDS))
def test_the_section_15_9_row_of_a_kind_is_what_the_filter_keeps_for_a_manager_or_viewer(
    kind: str,
) -> None:
    row = _rows().get(kind)
    assert row is not None, f"the §15.9 table has no row for `{kind}`"
    assert _fields(row) == NEUTRAL_FIELDS[kind] - {"kind", "severity", "message"}, f"kind {kind}"


@pytest.mark.parametrize(
    ("name", "neutral"), [("exchange", NEUTRAL_EXCHANGE), ("applied", NEUTRAL_APPLIED)]
)
def test_section_15_9_names_the_fields_of_each_nested_object_a_manager_or_viewer_receives(
    name: str, neutral: frozenset[str]
) -> None:
    listed = r"((?:`\w+`(?:,\s+and\s+|,\s+|\s+and\s+)?)+)"  # a, b and c; wrapped lines too
    said = re.search(rf"`{name}`[^|]*?\swith\s+only\s+{listed}", _section_15_9())
    assert said, f"§15.9 does not say which fields of `{name}` a Manager or Viewer receives"
    assert set(re.findall(r"`(\w+)`", said.group(1))) == neutral, f"fields of `{name}`"


def test_section_15_9_says_a_kill_switch_frame_without_its_state_reaches_only_the_owner() -> None:
    """A fault of the producer, counted under the reason `withheld_reason` gives it."""
    reason = withheld_reason({"kind": "kill_switch"}, MANAGER)
    said = f"a frame with no `kill_switch` object goes to the Owner only, counted as `{reason}`"
    assert said in _rows()["kill_switch"]


# -- feature flags: each key by its registry `visibility` (E42-T03, §15.9) ---------------------

#: Stands in for the registry's predicate: flag key -> the roles that may learn it. A real flag is
#: `all_roles` or `owner_only`; `ui.mgr`, for Managers alone, shows that the principal's own roles
#: are what is asked. A key not listed is one the registry does not define.
_FLAG_ROLES: dict[str, frozenset[str]] = {
    "ui.both": frozenset({"manager", "viewer"}),
    "ui.mgr": frozenset({"manager"}),
    "ops.owner": frozenset(),
}


def _visible(key: str, roles: frozenset[str]) -> bool:
    assert isinstance(key, str), key  # never asked about a key that is not a string
    return not roles.isdisjoint(_FLAG_ROLES.get(key, frozenset()))


_MIXED: dict[object, Any] = {"ui.both": True, "ui.mgr": 50, "ops.owner": False, "x.y": "on", 7: 1}
_FLAG_FRAME = {"kind": "feature_flags", "severity": "info", "message": "m", "feature_flags": _MIXED}


@pytest.mark.parametrize(
    ("who", "keys"),
    [
        (MANAGER, {"ui.both": True, "ui.mgr": 50}),
        (VIEWER, {"ui.both": True}),
        (principal("viewer", "manager"), {"ui.both": True, "ui.mgr": 50}),
    ],
    ids=["manager", "viewer", "both"],
)
def test_a_flag_frame_carries_only_the_keys_the_role_may_learn(
    who: PrincipalSnapshot, keys: dict[str, Any]
) -> None:
    """An `owner_only` key, a key the registry does not define and a key that is not a string
    are left out; `kind`, `severity` and `message` stay."""
    before = copy.deepcopy(_FLAG_FRAME)
    view = system_view(_FLAG_FRAME, who, flag_visible=_visible)
    assert view == {
        "kind": "feature_flags",
        "severity": "info",
        "message": "m",
        "feature_flags": keys,
    }
    assert _FLAG_FRAME == before
    assert view is not None
    validate(_frame(view))


def test_a_flag_frame_the_role_may_learn_whole_is_passed_on_as_is() -> None:
    body = {"kind": "feature_flags", "message": "m", "feature_flags": {"ui.both": 1, "ui.mgr": 0}}
    assert system_view(body, MANAGER, flag_visible=_visible) is body


@pytest.mark.parametrize(
    "flags",
    [{"ops.owner": True}, {"x.y": True}, {7: True}, {}, ["ui.both"], "ui.both", None, "absent"],
    ids=["owner-only", "undefined", "not-a-string", "empty", "list", "str", "null", "absent"],
)
@pytest.mark.parametrize("who", [MANAGER, VIEWER], ids=["manager", "viewer"])
def test_a_flag_frame_left_with_no_key_reaches_only_the_owner(
    flags: Any, who: PrincipalSnapshot
) -> None:
    body = {"kind": "feature_flags", "message": "m"} | (
        {} if flags == "absent" else {"feature_flags": flags}
    )
    assert system_view(body, who, flag_visible=_visible) is None
    assert system_view(body, OWNER, flag_visible=_visible) is body


@pytest.mark.parametrize("who", [MANAGER, VIEWER], ids=["manager", "viewer"])
def test_without_a_predicate_no_manager_or_viewer_learns_a_flag(who: PrincipalSnapshot) -> None:
    """Nothing wired (the fake backend, a test rig): the Owner's alone, as before E42-T03."""
    health = {"kind": "health", "health": "healthy", "feature_flags": {"ui.both": True}}
    assert system_view(_FLAG_FRAME, who) is None
    assert system_view(health, who) == {"kind": "health", "health": "healthy"}
    assert system_view(_FLAG_FRAME, OWNER) is _FLAG_FRAME and system_view(health, OWNER) is health


@pytest.mark.parametrize("who", [OWNER, principal("owner", "manager")], ids=["owner", "both"])
def test_the_owner_receives_every_flag_frame_whole(who: PrincipalSnapshot) -> None:
    def nothing(key: str, roles: frozenset[str]) -> bool:
        return False

    for flag_visible in (None, _visible, nothing):
        assert system_view(_FLAG_FRAME, who, flag_visible=flag_visible) is _FLAG_FRAME


def test_a_principal_with_no_role_learns_no_flag_even_one_every_role_may() -> None:
    def every(key: str, roles: frozenset[str]) -> bool:
        return True

    health = {"kind": "health", "health": "healthy", "feature_flags": {"ui.both": True}}
    for body in (_FLAG_FRAME, health):
        assert system_view(body, DENY_ALL, flag_visible=every) is None
        assert system_view(body, None, flag_visible=every) is None


@pytest.mark.parametrize(
    ("flags", "kept"),
    [
        ({"ui.both": True, "ops.owner": True, "x.y": 1}, {"feature_flags": {"ui.both": True}}),
        ({"ops.owner": True, "x.y": 1}, {}),  # none left: the field is left out, the frame is not
        ({}, {}),
        ("ui.both", {}),
    ],
    ids=["mixed", "none-visible", "empty", "not-a-map"],
)
def test_a_health_frame_carries_the_flag_keys_the_role_may_learn(
    flags: Any, kept: dict[str, Any]
) -> None:
    """The `system` snapshot is a `health` frame (§6.2, §12.1): it carries the set the role may
    learn, cut as a `feature_flags` frame is."""
    body = {"kind": "health", "health": "healthy", "feature_flags": flags}
    view = system_view(body, VIEWER, flag_visible=_visible)
    assert view == {"kind": "health", "health": "healthy"} | kept
    assert view is not None
    validate(_frame(view))


def test_a_health_frame_whose_flags_the_role_may_all_learn_is_passed_on_as_is() -> None:
    body = {"kind": "health", "health": "healthy", "feature_flags": {"ui.both": True}}
    assert system_view(body, VIEWER, flag_visible=_visible) is body


_OWNER_ONLY = frozenset({"actions"})
_OWNER_ONLY_STATE = frozenset({"engaged_by", "engaged_by_username", "reason"})
_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=4),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=4), inner),
    max_leaves=5,
)
_IDS = st.lists(st.sampled_from([str(ACC_A), str(ACC_B), str(ACC_B).upper(), "x"]), max_size=3)
_PART_KEYS = st.sampled_from(["name", "state", "detail", "last_good_at", "x"])
_NESTED_KEYS = st.sampled_from(
    ["public_ws", "rest", "forced_coalesce", "degraded_topics", "uid", "rate_budget_free_pct"]
)
_STATE_KEYS = st.sampled_from([*sorted(_SCHEMA["$defs"]["killSwitch"]["properties"]), "x"])
_FLAG_KEYS = st.sampled_from([*sorted(_FLAG_ROLES), "x.y"]) | st.integers() | st.text(max_size=4)
_SYMBOLS = st.lists(st.sampled_from(["BTCUSDT", "ETHUSDT"]), max_size=2)


def _body(
    kind: str, extra: dict[str, Any], state: Any, parts: Any, nested: Any, flags: Any, symbols: Any
) -> dict[str, Any]:
    """The drawn fields over `extra`; `exchange` and `applied` take the one `nested` draw."""
    drawn = {"kind": kind, "kill_switch": state, "components": parts, "feature_flags": flags}
    return extra | drawn | {"affected_symbols": symbols, "exchange": nested, "applied": nested}


#: Every body of the property tests: any kind of §15.9, whatever shape each of its fields takes;
#: an empty `components`, `affected_symbols` or `applied` is drawn on purpose, not left to chance.
BODIES = st.builds(
    _body,
    kind=st.sampled_from(sorted(NEUTRAL_FIELDS)),
    extra=st.dictionaries(
        st.sampled_from(sorted(_SCHEMA["properties"])) | st.text(max_size=6), _VALUES
    ),
    state=st.dictionaries(_STATE_KEYS, _VALUES | _IDS | _IDS.map(tuple)) | _VALUES,
    parts=st.builds(list)
    | st.lists(st.dictionaries(_PART_KEYS, _VALUES), max_size=3).flatmap(
        lambda parts: st.sampled_from([parts, tuple(parts)])
    )
    | _VALUES,
    nested=st.builds(dict) | st.dictionaries(_NESTED_KEYS, _VALUES) | _VALUES,
    flags=st.dictionaries(_FLAG_KEYS, _VALUES) | _VALUES,
    symbols=st.builds(list) | _SYMBOLS | _VALUES,
)


@settings(max_examples=200, deadline=None)
@given(
    body=BODIES,
    flag_visible=st.sampled_from([None, _visible]),
    who=st.sampled_from([MANAGER, VIEWER, principal("manager"), principal("viewer", "manager")]),
)
def test_no_manager_or_viewer_view_carries_an_owner_only_field_or_a_foreign_account(
    body: dict[str, Any], flag_visible: Any, who: PrincipalSnapshot
) -> None:
    kind = body["kind"]
    view = system_view(body, who, flag_visible=flag_visible)
    if view is None:
        return
    assert set(view) <= NEUTRAL_FIELDS[kind] and not set(view) & _OWNER_ONLY
    shown = view.get("feature_flags")
    assert shown or kind != "feature_flags"  # a flag frame is never sent without a key
    if shown is not None:  # a flag key only if the role may learn it, and never an empty map
        assert flag_visible is not None and shown
        assert all(isinstance(k, str) and _visible(k, who.roles) for k in shown)
    for item in view.get("components") or ():
        assert set(item) <= {"name", "state", "last_good_at"}  # never `detail`
    assert set(view.get("exchange") or ()) <= set(_EXCHANGE)  # never `uid`
    assert set(view.get("applied") or ()) <= set(_APPLIED)
    held = view.get("kill_switch")
    if held is None:
        return
    assert set(held) <= NEUTRAL_KILL_SWITCH | {"exchange_account_ids"}
    assert not set(held) & _OWNER_ONLY_STATE
    viewable = {str(g.exchange_account_id) for g in who.account_grants if g.can_view}
    assert set(held.get("exchange_account_ids") or ()) <= viewable
