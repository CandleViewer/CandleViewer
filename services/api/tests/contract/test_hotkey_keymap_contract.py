"""#305 (E10-S02), contract first: the hotkey profile contract is the client's keymap.

`22`'s `HotkeyBinding.action` takes the command ids of `apps/web/src/keymap/keymap.json`, and a
binding's `scope` is fixed by its command's `context` through the table in the `scope` description,
one scope per `KeymapContext` of `keymap.ts`. These tests pin that table and the
`listHotkeyProfiles` example to the client, the profile store's copy of the table included, so a
new context, a renamed id or a changed default chord fails here rather than leaving a parallel
vocabulary behind (BQ-2). They pin the arm and the confirm to it too (SEC-305C-02, BQ-5):
`requires_arm` only on the forced class, `confirm` on each destructive command."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from candleviewer.api._generated.openapi_models import HotkeyBinding, HotkeyBindingAuditInput
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
