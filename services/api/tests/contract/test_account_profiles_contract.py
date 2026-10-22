"""Contract (#906, E28-T02): a profile body carries exactly the stored columns of `account_profiles`
(C-6.1, C-6.3). Every body schema is closed, the generated models hold exactly its members, the
body takes the documented shapes and no other, and 24 section 9.2 maps each member to a column."""

from __future__ import annotations

import copy
import dataclasses
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.accounts import profiles as domain
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.storage.repositories import account_profiles as store

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_BASE = "urn:cv:openapi"
_REF = "#/components/schemas/"
_REGISTRY = Registry().with_resource(
    _BASE, Resource.from_contents(_SPEC, default_specification=DRAFT202012)
)
_DOCS = Path(__file__).resolve().parents[4] / "docs" / "plan"
_DOC_21 = (_DOCS / "21-database-schema.md").read_text(encoding="utf-8")
_DOC_24 = (_DOCS / "24-internal-schemas.md").read_text(encoding="utf-8")
#: `account_profiles` in 21 section 3.2.4: its columns, defaults and CHECKs.
(_DDL,) = re.findall(
    r"CREATE TABLE account_profiles \((.*?)CREATE UNIQUE INDEX ux_ap_name", _DOC_21, re.DOTALL
)
#: The writable schemas of a profile: each maps to stored columns and refuses what it does not name.
_BODY = (
    "AccountProfileInput ProfileSizing ProfileStopLoss ProfileTakeProfit "
    "ProfileTakeProfitRung ProfileRiskCaps"
).split()
_GONE = object()  # an edit that removes the member
_STOP = {"unit": "ticks", "value": "20"}
_ID = "0b5f6d0e-28a1-4c1e-9e01-000000000001"
_OWNED = set(_SCHEMAS["AccountProfile"]["properties"]) - {"profile"}  # a body never names them
#: The lists bounded beyond the columns, which hold any length (24 section 9.2): an entry, the most.
_BOUNDED: dict[str, tuple[Any, int]] = {
    "take_profit_ladder": ({"qty_pct": "5", "r": "1"}, 10),
    "allowed_symbols": ("BTCUSDT", 500),
    "blocked_symbols": ("ETHUSDT", 500),
}
#: A listed symbol and an anchored suffix are entries; the others are not: `*` and `**`, another
#: quote, a suffix not in front, lowercase, a 17-letter stem, a stray letter before and after.
_LONGEST = "A" * 16 + "USDT"  # the longest stem the contract takes, on its own and behind a `*`
_LISTED = ["BTCUSDT", "1000PEPEUSDT", "*USDT", "*PEPEUSDT", _LONGEST, f"*{_LONGEST}"]
_UNLISTED = "* **USDT BTCUSDC *BTC btcusdt ABCDEFGHIJKLMNOPQUSDT xBTCUSDT BTCUSDTx".split()
#: What each schema requires, in the order `22-api-openapi.yaml` lists it: a body (an answer, for
#: `AccountProfile`) without one is invalid, so a list that shrinks or grows is a contract change.
_REQUIRED = {
    "ProfileSizing": "mode",
    "ProfileStopLoss": "unit",
    "ProfileTakeProfit": "unit value",
    "ProfileTakeProfitRung": "qty_pct r",
    "AccountProfileInput": "name leverage sizing",
    "AccountProfile": "id exchange_account_id version created_at updated_at warnings profile",
}
#: (the edits to the create example, whether the body is still valid); an edit key is a dotted path.
_CASES: dict[str, tuple[dict[str, object], bool]] = {
    "the_create_example_an_atr_stop_and_an_r_multiple_target": ({}, True),
    "ticks_stop_with_its_value": ({"stop_loss": _STOP}, True),
    "take_profit_null": ({"take_profit": None}, True),
    "all_symbols_with_no_list": ({"all_symbols": True, "allowed_symbols": []}, True),
    "unknown_member": ({"trailing_stop": _STOP}, False),
    "removed_member_of_sizing": ({"sizing.round_to_lot": True}, False),
    "removed_member_of_risk_caps": ({"risk_caps.max_consecutive_losses": 3}, False),
    "read_only_version": ({"version": 2}, False),
    "read_only_is_active": ({"is_active": True}, False),
    "read_only_id": ({"id": _ID}, False),
    "read_only_exchange_account_id": ({"exchange_account_id": _ID}, False),
    "risk_based_without_a_stop": ({"stop_loss": _GONE}, False),
    "atr_stop_without_its_multiple": ({"stop_loss.atr_multiple": _GONE}, False),
    "ticks_stop_without_its_value": ({"stop_loss": {"unit": "ticks"}}, False),
    "stop_in_r_multiple": ({"stop_loss": {"unit": "r_multiple", "value": "2"}}, False),
    "take_profit_in_price": ({"take_profit": {"unit": "price", "value": "70000"}}, False),
    "fixed_qty_without_qty": ({"sizing": {"mode": "fixed_qty"}}, False),
    "fixed_notional_without_its_amount": ({"sizing": {"mode": "fixed_notional"}}, False),
    "fixed_notional_with_its_amount": (
        {"sizing": {"mode": "fixed_notional", "notional_usd": "100"}},
        True,
    ),
    "pct_equity_without_its_share": ({"sizing": {"mode": "pct_equity"}}, False),
    "pct_equity_with_its_share": ({"sizing": {"mode": "pct_equity", "pct": "5"}}, True),
    "risk_based_without_an_amount": ({"sizing.risk_per_trade_pct": _GONE}, False),
    "risk_based_with_only_the_usd_amount": (
        {"sizing": {"mode": "risk_based", "risk_per_trade_usd": "50"}},
        True,
    ),
    "request_time_sizing_mode": ({"sizing": {"mode": "pct_position", "pct": "5"}}, False),
    "portfolio_margin": ({"margin_mode": "portfolio"}, False),
    "native_stop_off": ({"require_native_stop": False}, False),
    "all_symbols_with_a_list": ({"all_symbols": True}, False),
    "no_open_positions_allowed": ({"risk_caps.max_open_positions": 0}, False),
    "too_many_open_positions": ({"risk_caps.max_open_positions": 51}, False),
}
for _name, (_entry, _bound) in _BOUNDED.items():  # each list at its bound, and one past it
    _CASES[f"{_bound}_{_name}"] = ({_name: [_entry] * _bound}, True)
    _CASES[f"{_bound + 1}_{_name}"] = ({_name: [_entry] * (_bound + 1)}, False)


def _valid(name: str, value: object) -> bool:
    """Whether `value` is a valid `name` component, the whole spec being the `$ref` registry."""
    return Draft202012Validator(
        {"$ref": f"{_BASE}#/components/schemas/{name}"},
        registry=_REGISTRY,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).is_valid(value)


def _example() -> dict[str, Any]:
    """A copy of the create operation's `riskBased` body."""
    post = _SPEC["paths"]["/exchange-accounts/{accountId}/profiles"]["post"]
    body: dict[str, Any] = copy.deepcopy(
        post["requestBody"]["content"]["application/json"]["examples"]["riskBased"]["value"]
    )
    return body


def _changed(edits: dict[str, object]) -> dict[str, Any]:
    """The create example, each dotted member set or removed (`_GONE`)."""
    body = _example()
    for path, value in edits.items():
        *parents, leaf = path.split(".")
        node = body
        for key in parents:
            node = node[key]
        if value is _GONE:
            del node[leaf]
        else:
            node[leaf] = value
    return body


def _target(prop: dict[str, Any]) -> dict[str, Any]:
    """The schema a member holds: its one `$ref`, or the non-null branch of its `oneOf`."""
    branch = next((b for b in prop.get("oneOf", [prop]) if b.get("type") != "null"), prop)
    target: dict[str, Any] = (
        _SCHEMAS[branch["$ref"].rsplit("/", 1)[1]] if "$ref" in branch else branch
    )
    return target


def _nullable(prop: dict[str, Any]) -> bool:
    types = prop.get("type", [])
    return "null" in ([types] if isinstance(types, str) else types) or any(
        branch.get("type") == "null" for branch in prop.get("oneOf", [])
    )


def _filled(schema: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """`body` with each member it leaves out set to its default, or `None` where nullable."""
    out: dict[str, Any] = {}
    for name, prop in schema["properties"].items():
        if name in body:
            nested = isinstance(body[name], dict)
            out[name] = _filled(_target(prop), body[name]) if nested else body[name]
        elif "default" in prop:
            out[name] = prop["default"]
        elif _nullable(prop):
            out[name] = None
    return out


def _unset(schema: dict[str, Any], value: dict[str, Any], path: str = "") -> list[str]:
    """The members of `schema`, at any depth, that `value` does not carry."""
    missing = [f"{path}{name}" for name in schema["properties"] if name not in value]
    for name, member in value.items():
        if isinstance(member, dict):
            missing += _unset(_target(schema["properties"][name]), member, f"{path}{name}.")
    return missing


def _leaves(schema: dict[str, Any], prefix: str = "") -> dict[str, dict[str, Any]]:
    """The members of `schema` that hold no object, by dotted path. An array of objects is one,
    and so is each of its `name[].member`."""
    out: dict[str, dict[str, Any]] = {}
    for name, prop in schema["properties"].items():
        target = _target(prop)
        items = _target(target["items"]) if target.get("type") == "array" else {}
        if "properties" in target:
            out |= _leaves(target, f"{prefix}{name}.")
        else:
            out[f"{prefix}{name}"] = prop
            out |= _leaves(items, f"{prefix}{name}[].") if "properties" in items else {}
    return out


def _nodes(root: Any) -> Iterator[dict[str, Any]]:
    """Every object below `root`, each `$ref` into the schemas followed once."""
    todo, seen = [root], {""}
    while todo:
        node = todo.pop()
        if isinstance(node, list):
            todo.extend(node)
        elif isinstance(node, dict):
            yield node
            todo.extend(node.values())
            ref = node.get("$ref", "")
            if isinstance(ref, str) and ref not in seen:
                seen.add(ref)
                todo.append(_SCHEMAS[ref.rsplit("/", 1)[1]])


def _projection() -> list[tuple[str | None, str | None, str | None, bool]]:
    """24 section 9.2's REST projection: (REST member, domain field, column, read-only) rows."""
    table = _DOC_24.split("**REST projection (E28-T02, #906).**", 1)[1].split("\n\n", 2)[1]
    rows: list[tuple[str | None, str | None, str | None, bool]] = []
    for line in table.splitlines()[2:]:  # past the header and its rule
        cells = [c.strip() for c in line.strip("|").split("|")][:3]
        rest, field, column = (
            None if c == "—" else c.removesuffix(" (read-only)").strip("`") for c in cells
        )
        rows.append((rest, field, column, cells[0].endswith(" (read-only)")))
    return rows


def _enums(pattern: str, text: str) -> dict[str, list[str]]:  # name -> the quoted values after it
    return {m[1]: re.findall(r"'(\w+)'", m[2]) for m in re.finditer(pattern, text)}


@pytest.mark.parametrize("name", _BODY)
def test_every_profile_body_schema_refuses_unknown_members(name: str) -> None:
    assert _SCHEMAS[name]["additionalProperties"] is False
    assert getattr(api, name).model_config["extra"] == "forbid"


def test_generated_profile_models_have_exactly_the_contract_members() -> None:
    for name in (*_BODY, "AccountProfile"):
        assert set(getattr(api, name).model_fields) == set(_SCHEMAS[name]["properties"]), name
    assert api.AccountProfile.model_fields["profile"].annotation is api.AccountProfileInput
    native_stop = api.AccountProfileInput.model_fields["require_native_stop"].annotation
    assert get_origin(native_stop) is Literal  # the stored invariant is a constant, `Literal[True]`
    assert get_args(native_stop) == (True,)
    assert _OWNED.isdisjoint(_SCHEMAS["AccountProfileInput"]["properties"])
    assert _OWNED.isdisjoint(api.AccountProfileInput.model_fields)


def test_the_create_example_is_a_body_and_its_defaults_make_a_stored_profile() -> None:
    assert _valid("AccountProfileInput", _example())
    profile = _filled(_SCHEMAS["AccountProfileInput"], _example())
    assert _unset(_SCHEMAS["AccountProfileInput"], profile) == []  # a default or a null, each
    stored = dict(id=_ID, exchange_account_id=_ID, version=1, warnings=[], profile=profile)
    stored |= dict.fromkeys(("created_at", "updated_at"), "2026-10-21T09:30:00Z")
    assert _valid("AccountProfile", stored)
    assert not _valid("AccountProfile", {**stored, "profile": {**profile, "is_active": True}})


@pytest.mark.parametrize(("edits", "valid"), list(_CASES.values()), ids=list(_CASES))
def test_the_body_schema_takes_exactly_the_documented_shapes(
    edits: dict[str, object], valid: bool
) -> None:
    assert _valid("AccountProfileInput", _changed(edits)) is valid


@pytest.mark.parametrize("name", _BOUNDED)
def test_the_generated_model_takes_a_list_up_to_its_bound_and_no_more(name: str) -> None:
    entry, bound = _BOUNDED[name]
    taken = api.AccountProfileInput.model_validate(_changed({name: [entry] * bound}))
    assert len(getattr(taken, name)) == bound
    with pytest.raises(ValidationError) as refused:  # which the API answers 422
        api.AccountProfileInput.model_validate(_changed({name: [entry] * (bound + 1)}))
    assert [(e["loc"], e["type"]) for e in refused.value.errors()] == [((name,), "too_long")]


def test_every_rest_member_is_one_domain_field_and_one_column() -> None:
    rows = _projection()
    rest, fields, columns = ([row[i] for row in rows if row[i]] for i in range(3))
    assert set(rest) == set(_leaves(_SCHEMAS["AccountProfileInput"])) | _OWNED
    assert {row[0] for row in rows if row[3]} == _OWNED  # the read-only rows
    rung = {"tp_ladder[].qty_pct", "tp_ladder[].r"}
    assert set(fields) == set(domain.AccountProfile.model_fields) | rung
    stored = {f.name for f in dataclasses.fields(store.AccountProfileValues)}
    stored |= {f.name for f in dataclasses.fields(store.AccountProfileRow)}
    stored -= {"values", "created_by", "updated_by", "deleted_at"}  # bookkeeping, mapped to nothing
    assert set(columns) == stored | {"tp_ladder[].pct", "tp_ladder[].r"}
    assert all(len(cells) == len(set(cells)) for cells in (rest, fields, columns))  # one to one
    renamed = {f for _, f, c, _ in rows if f and c and f not in c and c not in f}
    assert renamed == {"tp_ladder[].qty_pct", "denied_symbols"}  # a column is named for its field
    assert [row[:3] for row in rows if None in row[:3]] == [
        ("created_at", None, "created_at"),
        ("warnings", None, None),
        (None, "qty_rounding", None),
    ]


def test_members_with_no_column_are_gone() -> None:
    removed = (
        "trailing_stop default_tpsl_mode round_to_lot max_notional_usd atr_bar_type atr_param "
        "max_consecutive_losses lockout_minutes_after_breach is_active"
    ).split()
    nodes = list(_nodes(_SCHEMAS["AccountProfile"]))
    named = {n for node in nodes for n in (*node.get("properties", {}), *node.get("required", []))}
    assert "risk_caps" in named  # the walk reached the nested members
    assert named.isdisjoint(removed)
    text = _SCHEMAS["SizingMode"]["description"]  # the envelope moved `sizing` under `profile`
    assert "`AccountProfile.profile.sizing`" in text and "`AccountProfile.sizing`" not in text


def test_profile_enums_are_the_table_and_the_model() -> None:
    types = _enums(r"CREATE TYPE (\w+)\s+AS ENUM \(([^)]*)\)", _DOC_21)
    checks = _enums(r"CHECK \((\w+) IN \(([^)]*)\)\)", _DDL)
    assert re.search(r"CONSTRAINT ap_sl_unit\s+CHECK \(sl_offset_unit <> 'r_multiple'\)", _DDL)
    stop = [unit for unit in types["offset_unit"] if unit != "r_multiple"]
    for schema, table, model in (
        ("ProfileSizingMode", types["sizing_mode"], domain.SizingMode),
        ("ProfileTargetUnit", types["offset_unit"], domain.OffsetUnit),
        ("ProfileStopUnit", stop, domain.StopUnit),
        ("ProfileMarginMode", checks["margin_mode"], domain.MarginMode),
        ("PositionMode", checks["position_mode"], domain.PositionMode),
        ("TimeInForce", checks["time_in_force_default"], domain.TimeInForce),
    ):
        assert _SCHEMAS[schema]["enum"] == table == list(get_args(model)), schema
    assert _SCHEMAS["ProfileSizingMode"]["x-db-enum"] == "sizing_mode"
    assert _SCHEMAS["ProfileTargetUnit"]["x-db-enum"] == "offset_unit"
    assert "x-db-enum" not in _SCHEMAS["ProfileStopUnit"]  # a subset of `offset_unit`, not a mirror
    gates = {g["id"]: g for g in _SPEC["x-contract-validation"]["gates"]}
    covers = {c["schema"]: c["pg_type"] for c in gates["enum_parity_db"]["covers"]}
    mirrors = ("ProfileSizingMode", "ProfileTargetUnit")  # the parity gate has a row for each
    assert {s: covers[s] for s in mirrors} == {s: _SCHEMAS[s]["x-db-enum"] for s in mirrors}


def test_bounds_and_defaults_are_the_columns() -> None:
    column = {rest: col for rest, _, col, _ in _projection() if rest}
    defaults = dict(re.findall(r"^\s+(\w+)\s.*?\bDEFAULT ('[^']*'|[^\s,]+)", _DDL, re.MULTILINE))
    ranges = re.finditer(r"(\w+) BETWEEN (\d+) AND (\d+)", _DDL)
    bounds = {m[1]: (int(m[2]), int(m[3])) for m in ranges}
    leaves = _leaves(_SCHEMAS["AccountProfileInput"])
    # a list's default is `[]`, which is a NULL column; every other leaf with a default is compared
    scalar = {p: m["default"] for p, m in leaves.items() if m.get("default", []) != []}
    assert len(scalar) == 16  # so the loop below cannot pass by comparing nothing
    for path, default in scalar.items():
        assert str(default).lower() == defaults[column[path]].strip("'").lower(), path
    integers = (
        "stop_loss.atr_period risk_caps.max_open_positions risk_caps.max_concurrent_orders "
        "risk_caps.max_orders_per_minute slippage_tolerance_bps"
    ).split()
    for path in integers:
        assert (leaves[path]["minimum"], leaves[path]["maximum"]) == bounds[column[path]], path


def test_the_name_length_and_the_version_floor_are_the_columns() -> None:
    # `name` is bounded by `char_length(name)`, which the `BETWEEN` pattern above cannot read
    name = _SCHEMAS["AccountProfileInput"]["properties"]["name"]
    length = re.search(r"char_length\(name\) BETWEEN (\d+) AND (\d+)", _DDL)
    assert length and (name["minLength"], name["maxLength"]) == tuple(map(int, length.groups()))
    assert _SCHEMAS["AccountProfile"]["properties"]["version"]["minimum"] == 1  # `ap_version`


def test_symbol_entries_are_listed_symbols_or_anchored_usdt_suffixes() -> None:
    taken = [entry for entry in [*_LISTED, *_UNLISTED] if _valid("ProfileSymbolPattern", entry)]
    assert taken == _LISTED
    domain_pattern = get_args(domain.SymbolPattern)[1].pattern
    assert all(re.fullmatch(domain_pattern, entry) for entry in taken)  # REST never takes more
    members = _SCHEMAS["AccountProfileInput"]["properties"]
    assert [members[n]["items"] for n in ("allowed_symbols", "blocked_symbols")] == [
        {"$ref": f"{_REF}ProfileSymbolPattern"}
    ] * 2


def test_d11_all_symbols_is_explicit_and_an_empty_list_allows_nothing() -> None:
    members = _SCHEMAS["AccountProfileInput"]["properties"]
    allowed = members["allowed_symbols"]["description"]
    assert members["all_symbols"]["default"] is False
    assert allowed == "Empty without `all_symbols`, it allows nothing (decision D11)."
    texts = [n["description"] for n in _nodes(_SCHEMAS["AccountProfile"]) if "description" in n]
    assert allowed in texts  # the walk reached the members
    assert not [t for t in texts if isinstance(t, str) and "Empty means" in t]


def test_warnings_are_advice_in_a_set_open_to_readers() -> None:
    warning = _SCHEMAS["ProfileWarning"]
    code = warning["properties"]["code"]
    kinds = "all_symbols no_symbols sizing_below_min_order stop_beyond_liquidation"
    assert code["enum"] == kinds.split()
    assert warning["required"] == ["code", "message"]
    text = " ".join(code["description"].split())
    assert "Open-ended for readers" in text
    assert "or by the pattern `*USDT`;" in text and "also flags any other pattern" in text
    profile = _SCHEMAS["AccountProfile"]
    assert "warnings" in profile["required"]
    assert profile["properties"]["warnings"]["items"] == {"$ref": f"{_REF}ProfileWarning"}
    assert set(api.ProfileWarning.model_fields) == set(warning["properties"])


@pytest.mark.parametrize("name", _REQUIRED)
def test_a_profile_schema_requires_exactly_its_documented_members(name: str) -> None:
    assert _SCHEMAS[name]["required"] == _REQUIRED[name].split()


def test_the_documented_list_bounds_are_the_contract_bounds() -> None:
    heading = "**Two bounds no column states (E28-T02, #906).**"
    paragraph = _DOC_24.split(heading, 1)[1].split("\n\n", 1)[0]
    for name, (_, bound) in _BOUNDED.items():
        assert f"`{name}`" in paragraph and f"at most {bound} " in paragraph, name
