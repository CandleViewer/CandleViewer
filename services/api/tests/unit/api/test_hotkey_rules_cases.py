"""E10-T05 (#5211, BQ-4): the shared case fixture through the server's judge.

`packages/fixtures/golden/hotkeys/profile_cases.json` is one case table for the server's port of the
client's binding rules (`api/hotkey_rules.py`) and the client itself (`validate.ts`):
apps/web/test/keymap-server-parity.test.ts runs the same cases against `validate.ts`, so the port
and the client cannot drift apart unseen. Each profile case is sent as a body through
`judge_body`, the path a create or a replace takes, each binding with the scope 22's table gives
its command unless the case names one. The client's own default profile is built here as
`profileStore.ts`'s `input()` builds it, from `keymap.json` and 22's scope table, and the server
accepts it as it is, rewriting nothing.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.hotkey_profiles_models import judge_body
from candleviewer.api.hotkey_rules import (
    VOCABULARY,
    HotkeyBindingConflict,
    HotkeyBindingsInvalid,
    binding_atoms,
    is_single_letter,
    normalise_binding,
)

_REPO = Path(__file__).resolve().parents[5]
_CASES: dict[str, Any] = json.loads(
    (_REPO / "packages/fixtures/golden/hotkeys/profile_cases.json").read_text(encoding="utf-8")
)
_KEYMAP: dict[str, Any] = json.loads(
    (_REPO / "apps/web/src/keymap/keymap.json").read_text(encoding="utf-8")
)
#: 22's order of the `422` rules of one binding (`HotkeyProfileInput.bindings`).
RULES = (
    "unknown_action", "duplicate_action", "scope_mismatch", "params_not_allowed", "invalid_keys",
    "shape_mismatch", "bare_letter_dangerous", "reserved_key", "locked_command",
)  # fmt: skip
#: The rules the client's profile, a map of command id to binding, cannot express.
SERVER_ONLY = {"duplicate_action", "scope_mismatch", "params_not_allowed"}


def _scope_table() -> dict[str, str]:
    """22's `HotkeyBinding.scope` table, read from the parsed contract."""
    spec: Any = load_openapi_spec()
    scope = spec["components"]["schemas"]["HotkeyBinding"]["properties"]["scope"]
    return dict(re.findall(r"^\| `(\w+)` +\| `(\w+)` +\|$", scope["description"], re.M))


def client_default() -> list[dict[str, object]]:
    """`profileStore.ts`'s `input()` with no binding changed: every command of `keymap.json`, in
    its order, at its default, with the scope of 22's table and the keymap's `requiresArm` and
    `confirm`."""
    table = _scope_table()
    return [
        {"action": c["id"], "keys": c["defaultBinding"], "scope": table[c["context"]],
         "requires_arm": c.get("requiresArm") is True, "confirm": c.get("confirm") is True}
        for c in _KEYMAP["commands"]
    ]  # fmt: skip


def _body(case: dict[str, Any]) -> bytes:
    if case["bindings"] == "client_default":
        bindings = client_default()
    else:
        known = VOCABULARY.commands
        bindings = [
            {"scope": known[b["action"]].scope if b["action"] in known else "global", **b}
            for b in case["bindings"]
        ]
    return json.dumps({"name": "Case", "bindings": bindings}).encode("utf-8")


@pytest.mark.parametrize("case", _CASES["grammar"], ids=lambda c: repr(c["raw"]))
def test_the_grammar_reads_a_binding_as_validate_ts_does(case: dict[str, Any]) -> None:
    assert normalise_binding(case["raw"]) == case["canonical"]


@pytest.mark.parametrize("case", _CASES["atoms"], ids=lambda c: str(c["binding"]))
def test_a_binding_has_the_atoms_binding_atoms_gives(case: dict[str, Any]) -> None:
    assert binding_atoms(case["binding"]) == case["atoms"]


@pytest.mark.parametrize("case", _CASES["single_letter"], ids=lambda c: repr(c["binding"]))
def test_a_single_letter_is_what_is_single_letter_says(case: dict[str, Any]) -> None:
    """The client's verdict, but for a code point this Python's Unicode leaves unassigned (`Cn`):
    the browser's, newer, may call it a letter, and the port refuses no key on that (the rules
    module's docstring), so there it answers no."""
    rest = case["binding"].removeprefix("Shift+")
    unassigned = len(rest) == 1 and unicodedata.category(rest) == "Cn"
    assert is_single_letter(case["binding"]) is (case["single"] and not unassigned)


@pytest.mark.parametrize("case", _CASES["profiles"], ids=lambda c: str(c["id"]))
def test_the_server_judges_each_profile_case(case: dict[str, Any]) -> None:
    expect = case["expect"]
    if "accepted" in expect:
        judged = judge_body(_body(case))
        assert list(judged.rewritten) == expect["accepted"]["rewritten"]
        if "stored" in expect["accepted"]:
            assert judged.fields.bindings == expect["accepted"]["stored"]
        return
    if "invalid" in expect:
        with pytest.raises(HotkeyBindingsInvalid) as invalid:
            judge_body(_body(case))
        assert [(e["field"], e["rule"]) for e in invalid.value.errors] == [
            (e["field"], e["rule"]) for e in expect["invalid"]
        ]
        return
    with pytest.raises(HotkeyBindingConflict) as conflict:
        judge_body(_body(case))
    errors = conflict.value.errors
    assert [(e["field"], e["rule"]) for e in errors] == [
        (e["field"], "binding_conflict") for e in expect["conflict"]
    ]
    for error, item in zip(errors, expect["conflict"], strict=True):
        assert f"with {item['other']} " in error["message"]


def test_the_client_default_profile_is_stored_whole_at_its_defaults() -> None:
    (case,) = [c for c in _CASES["profiles"] if c["bindings"] == "client_default"]
    judged = judge_body(_body(case))
    defaults = {c["id"]: c["defaultBinding"] for c in _KEYMAP["commands"]}
    assert judged.fields.bindings == defaults and judged.rewritten == ()
    assert list(judged.fields.bindings) == list(VOCABULARY.commands)


def test_the_cases_cover_every_rule_and_the_server_only_ones_are_the_maps_blind_spots() -> None:
    """Each `422` rule, a conflict, a rewrite and an acceptance has a case; the cases vitest leaves
    out are exactly those whose rule the client's map of command id to binding cannot express."""
    profiles = _CASES["profiles"]
    rules = {e["rule"] for c in profiles for e in c["expect"].get("invalid", [])}
    assert rules == set(RULES)
    assert any("conflict" in c["expect"] for c in profiles)
    assert any(c["expect"].get("accepted", {}).get("rewritten") for c in profiles)
    for case in profiles:
        if "server_only" in case:
            assert {e["rule"] for e in case["expect"]["invalid"]} <= SERVER_ONLY, case["id"]
        else:
            assert not {e["rule"] for e in case["expect"].get("invalid", [])} & SERVER_ONLY
    assert len({c["id"] for c in profiles}) == len(profiles)
