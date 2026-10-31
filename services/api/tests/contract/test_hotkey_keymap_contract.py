"""#305 (E10-S02), contract first: the hotkey profile contract is the client's keymap.

`22`'s `HotkeyBinding.action` takes the command ids of `apps/web/src/keymap/keymap.json`, and a
binding's `scope` is fixed by its command's `context` through the table in the `scope` description,
one scope per `KeymapContext` of `keymap.ts`. These tests pin that table and the
`listHotkeyProfiles` example to the client, the profile store's copy of the table included, so a
new context, a renamed id or a changed default chord fails here rather than leaving a parallel
vocabulary behind (BQ-2). They pin the arm and the confirm to it too (SEC-305C-02, BQ-5):
`requires_arm` only on the forced class, `confirm` on each destructive command.

E10-T05 (#5211), the server half's contract: the profile is one closed object whose input refuses
unknown members (BQ-1), `22` names the five forced commands and the dangerous set it derives
`requires_arm` and `confirm` from, with no default (BQ-3), `keys` names the three locked commands
and no sequence (BQ-4), and the writes declare the ruled answers and headers (BQ-5, BQ-10, BQ-13).
The generated vocabulary file is the third side of the forced-class pin once it lands."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.api._generated.openapi_models import (
    HotkeyBinding,
    HotkeyBindingAuditInput,
    HotkeyProfile,
    HotkeyProfileInput,
)
from candleviewer.api.contract_conformance import load_openapi_spec

_KEYMAP = Path(__file__).resolve().parents[4] / "apps" / "web" / "src" / "keymap"
_SPEC: Any = load_openapi_spec()
_SCOPE = _SPEC["components"]["schemas"]["HotkeyBinding"]["properties"]["scope"]
#: The rows of the `scope` description's table: (`keymap.json` context, `scope`).
TABLE = re.findall(r"^\| `(\w+)` +\| `(\w+)` +\|$", _SCOPE.get("description", ""), re.M)
COMMANDS = {
    c["id"]: c
    for c in json.loads((_KEYMAP / "keymap.json").read_text(encoding="utf-8"))["commands"]
}
_UNION = re.search(
    r"export type KeymapContext =([^;]*);", (_KEYMAP / "keymap.ts").read_text(encoding="utf-8")
)
CONTEXTS = re.findall(r'"(\w+)"', _UNION.group(1)) if _UNION else []
_COPY = re.search(
    r"const SCOPE\b[^=]*=\s*\{([^}]*)\}", (_KEYMAP / "profileStore.ts").read_text(encoding="utf-8")
)
#: The rows of the profile store's copy of that table: (`keymap.json` context, `scope`).
STORE_TABLE = re.findall(r'^\s*(\w+): "(\w+)",$', _COPY.group(1), re.M) if _COPY else []
_LIST = _SPEC["paths"]["/settings/hotkeys"]["get"]["responses"]["200"]["content"]
EXAMPLE = [
    b
    for p in _LIST["application/json"]["examples"]["default"]["value"]["items"]
    for b in p["bindings"]
]
#: `ArmToken`'s forced class as keymap commands: each places an order (a submit, `placeOrder`,
#: reduce-only ones included). No other command is forced: the C-2.6 carve-out's cancels and closes,
#: the arm toggles, the kill switch, and every command that changes no order (BQ-5).
FORCED = {
    "chart.limit_at_price",
    "chart.market_order",
    "dom.market_click",
    "dom.stop_click",
    "ticket.submit",
}
#: The client's dangerous set (BQ-3): `audited` in `keymap.json`, equal to `DANGEROUS_COMMANDS`.
DANGEROUS = {cid for cid, c in COMMANDS.items() if c.get("audited") is True}


def test_contract_scope_table_names_every_keymap_context_once() -> None:
    contexts = [context for context, _ in TABLE]
    assert CONTEXTS, "keymap.ts declares no KeymapContext union"
    assert sorted(contexts) == sorted(set(CONTEXTS)), "the table and KeymapContext differ"
    assert len(contexts) == len(set(contexts)), "a context has two rows"


def test_contract_profile_store_scope_copy_is_the_scope_table() -> None:
    assert STORE_TABLE, "profileStore.ts declares no SCOPE rows"
    assert sorted(STORE_TABLE) == sorted(TABLE), "the store's SCOPE and the table differ"


def test_contract_every_keymap_command_context_is_a_table_row() -> None:
    assert {c["context"] for c in COMMANDS.values()} <= {context for context, _ in TABLE}


def test_contract_scope_table_maps_contexts_onto_distinct_enum_values() -> None:
    scopes = [scope for _, scope in TABLE]
    assert set(scopes) <= set(_SCOPE["enum"]), "a table scope is not a HotkeyBinding.scope value"
    assert len(scopes) == len(set(scopes)), "two contexts share a scope"


@pytest.mark.parametrize("binding", EXAMPLE, ids=lambda b: str(b["action"]))
def test_contract_list_example_binding_is_the_keymap_default(binding: dict[str, Any]) -> None:
    assert binding["action"] in COMMANDS, "the example names an id keymap.json does not have"
    command = COMMANDS[binding["action"]]
    assert (binding["keys"], binding["scope"]) == (
        command["defaultBinding"],
        dict(TABLE)[command["context"]],
    )
    assert HotkeyBinding.model_validate(binding).scope == binding["scope"]


@pytest.mark.parametrize("command_id", sorted(COMMANDS))
def test_contract_keymap_id_is_a_valid_action_and_audit_command_id(command_id: str) -> None:
    binding = HotkeyBinding(action=command_id, keys="F1", scope="global")
    audit = HotkeyBindingAuditInput(
        command_id=command_id, before="", after="", acknowledged_unsafe=False
    )
    assert binding.action == audit.command_id == command_id


def test_contract_requires_arm_is_declared_on_exactly_the_forced_class() -> None:
    armed = {cid for cid, c in COMMANDS.items() if c.get("requiresArm") is True}
    assert armed == FORCED
    # A cancel or a close is destructive in the keymap and protective by C-2.6: no arm holds it.
    assert not {cid for cid in armed if COMMANDS[cid]["destructive"]}


def test_contract_confirm_accompanies_every_destructive_command() -> None:
    confirm = {cid for cid, c in COMMANDS.items() if c.get("confirm") is True}
    assert {cid for cid, c in COMMANDS.items() if c["destructive"]} <= confirm
    assert confirm == DANGEROUS


def test_contract_list_example_names_bindings() -> None:
    assert EXAMPLE, "the listHotkeyProfiles example names no binding"


@pytest.mark.parametrize("binding", EXAMPLE, ids=lambda b: str(b["action"]))
def test_contract_list_example_arm_and_confirm_follow_the_keymap(binding: dict[str, Any]) -> None:
    model = HotkeyBinding.model_validate(binding)
    assert model.requires_arm is (binding["action"] in FORCED)
    assert model.confirm is (COMMANDS[binding["action"]].get("confirm") is True)


_SCHEMAS = _SPEC["components"]["schemas"]
_MEMBERS = _SCHEMAS["HotkeyBinding"]["properties"]
_ITEMS: list[dict[str, Any]] = _LIST["application/json"]["examples"]["default"]["value"]["items"]
#: The `422` rules of one binding, in the order `HotkeyProfileInput.bindings` names the first
#: broken one by (BQ-2, BQ-4): the server's own checks, then the client's (`validate.ts`).
_RULES = (
    *("unknown_action", "duplicate_action", "scope_mismatch", "params_not_allowed"),
    *("invalid_keys", "shape_mismatch", "bare_letter_dangerous", "reserved_key", "locked_command"),
)
_PROFILE = "/settings/hotkeys/{hotkeyProfileId}"
#: Every answer each operation declares (BQ-5, BQ-12, BQ-13): the list keeps its unanswered `404`.
_ANSWERS = {
    ("get", "/settings/hotkeys"): {"200", "401", "403", "404", "503"},
    ("post", "/settings/hotkeys"): {"201", "401", "403", "409", "413", "422", "503"},
    ("put", _PROFILE): {"200", "401", "403", "404", "409", "412", "413", "422", "503"},
    ("delete", _PROFILE): {"204", "401", "403", "404", "409", "503"},
    ("post", f"{_PROFILE}/activate"): {"200", "401", "403", "404", "503"},
}
#: The headers each answer declares (BQ-3, BQ-10, BQ-13).
_HEADERS = {
    ("post", "/settings/hotkeys", "201"): {"ETag", "Hotkey-Bindings-Rewritten"},
    ("put", _PROFILE, "200"): {"ETag", "Hotkey-Bindings-Rewritten"},
    ("put", _PROFILE, "412"): {"ETag"},
    ("post", f"{_PROFILE}/activate", "200"): {"ETag"},
}


def _named(description: str) -> set[str]:
    """The keymap command ids a description names, each in backticks."""
    return {token for token in re.findall(r"`([a-z0-9_.]+)`", description) if token in COMMANDS}


def _text(description: str) -> str:
    return " ".join(description.split())


def test_contract_requires_arm_names_exactly_the_forced_class_and_has_no_default() -> None:
    """BQ-3: `22` names the five, which are the keymap's `requiresArm`. No default: a binding that
    left the flag out asked for an arm on `dom.cancel_all`."""
    assert _named(_MEMBERS["requires_arm"]["description"]) == FORCED
    assert "default" not in _MEMBERS["requires_arm"]


def test_contract_confirm_names_exactly_the_dangerous_set_and_has_no_default() -> None:
    assert _named(_MEMBERS["confirm"]["description"]) == DANGEROUS
    assert "default" not in _MEMBERS["confirm"]


def test_contract_keys_names_the_locked_commands_its_rules_and_no_sequence() -> None:
    """BQ-4: the commands the keymap does not let a user remap are named; the client binds no key
    sequence, so none is in the grammar."""
    keys = _text(_MEMBERS["keys"]["description"])
    locked = {cid for cid, c in COMMANDS.items() if c.get("editable") is False}
    assert locked == {"global.palette", "chart.cancel_drawing", "ticket.clear"}
    assert locked <= _named(keys)
    assert "Esc Esc" not in keys
    assert all(f"`{rule}`" in keys for rule in _RULES[4:])


def test_contract_bindings_name_each_rule_once_in_its_order() -> None:
    bindings = _text(_SCHEMAS["HotkeyProfileInput"]["properties"]["bindings"]["description"])
    assert [r for r in re.findall(r"`([a-z_]+)`", bindings) if r in _RULES] == list(_RULES)


def test_contract_hotkey_profile_is_one_closed_object_with_every_member_required() -> None:
    """BQ-1: flattened as `Watchlist` is, so `HotkeyProfileInput` can refuse unknown members
    (SEC-305C-01) without refusing the profile's own."""
    profile = _SCHEMAS["HotkeyProfile"]
    assert "allOf" not in profile
    assert profile["additionalProperties"] is False
    assert set(profile["required"]) == set(profile["properties"])
    assert profile["properties"]["version"]["readOnly"] is True
    assert _SCHEMAS["HotkeyProfileInput"]["additionalProperties"] is False
    assert _SCHEMAS["HotkeyBinding"]["additionalProperties"] is False


@pytest.mark.parametrize("item", _ITEMS, ids=lambda p: str(p["name"]))
def test_contract_list_example_is_a_whole_hotkey_profile(item: dict[str, Any]) -> None:
    assert str(HotkeyProfile.model_validate(item).id) == item["id"]


@pytest.mark.parametrize("member", ["is_active", "scheme_base", "requires_arm"])
def test_generated_profile_input_refuses_an_unknown_member(member: str) -> None:
    body = {"name": "CandleViewer Default", "bindings": _ITEMS[0]["bindings"]}
    assert HotkeyProfileInput.model_validate(body).name == body["name"]
    with pytest.raises(ValidationError) as refused:
        HotkeyProfileInput.model_validate({**body, member: True})
    assert [e["type"] for e in refused.value.errors()] == ["extra_forbidden"]


def test_generated_profile_refuses_an_unknown_member() -> None:
    with pytest.raises(ValidationError) as refused:
        HotkeyProfile.model_validate({**_ITEMS[0], "deleted_at": None})
    assert [e["type"] for e in refused.value.errors()] == ["extra_forbidden"]


@pytest.mark.parametrize(("method", "path"), sorted(_ANSWERS))
def test_contract_hotkey_operation_declares_the_ruled_answers(method: str, path: str) -> None:
    assert set(_SPEC["paths"][path][method]["responses"]) == _ANSWERS[(method, path)]


@pytest.mark.parametrize(("method", "path", "status"), sorted(_HEADERS))
def test_contract_hotkey_answer_declares_its_headers(method: str, path: str, status: str) -> None:
    headers = _SPEC["paths"][path][method]["responses"][status]["headers"]
    assert set(headers) == _HEADERS[(method, path, status)]
    assert headers["ETag"] == {"$ref": "#/components/headers/HotkeyProfileETag"}


def test_contract_my_keymap_answers_the_active_profile() -> None:
    text = _text(_SPEC["paths"]["/me/keymap"]["get"]["description"])
    assert "While the caller has no active profile, `hotkey_profile_id` is absent" in text
    assert "or the hotkey profile store cannot be read; nothing is served" in text
