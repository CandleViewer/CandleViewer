"""`api/hotkey_rules.py` (E10-T05, #5211) beyond the shared case fixture: the vocabulary it loads
and refuses, each branch of the conflict check on a vocabulary built for it (a shadow declared on
either side, overlapping focus contexts, two Global commands), the 20-item bound, the read path
(keymap order, derived members, unknown ids dropped) and the grammar's invariants. The fixture
itself, which vitest runs against `validate.ts` too, is tests/unit/api/test_hotkey_rules_cases.py's.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.api import hotkey_rules as rules
from candleviewer.api.hotkey_rules import (
    VOCABULARY,
    Command,
    HotkeyBindingConflict,
    HotkeyBindingsInvalid,
    Vocabulary,
    judge,
    load_vocabulary,
    normalise_binding,
    parse_vocabulary,
    read_bindings,
    shape_of,
)


class _Entry:
    """One body entry as the generated `HotkeyBinding` holds it."""

    def __init__(self, action: str, keys: str, scope: str, **kw: Any) -> None:
        self.action, self.keys, self.scope = action, keys, scope
        self.requires_arm: bool | None = kw.get("requires_arm")
        self.confirm: bool | None = kw.get("confirm")
        self.params: dict[str, Any] | None = kw.get("params")


def _command(cid: str, context: str, default: str, **kw: Any) -> Command:
    focus = frozenset(kw.get("focus", {context}))
    return Command(
        cid, context, context.lower(), focus, default, kw.get("editable", True),
        kw.get("override", False), frozenset(kw.get("shadows", ())), kw.get("dangerous", False),
        kw.get("arm", False), kw.get("confirm", False),
    )  # fmt: skip


def _vocabulary(*commands: Command) -> Vocabulary:
    return Vocabulary({c.id: c for c in commands}, {"Ctrl+W": "browser"}, frozenset({"Esc"}))


def _entry(vocab: Vocabulary, action: str, keys: str) -> _Entry:
    return _Entry(action, keys, vocab.commands[action].scope)


def _conflict(vocab: Vocabulary, *entries: tuple[str, str]) -> list[dict[str, str]] | None:
    try:
        judge([_entry(vocab, action, keys) for action, keys in entries], vocab)
    except HotkeyBindingConflict as conflict:
        return conflict.errors
    return None


def test_the_loaded_vocabulary_is_the_generated_file_in_keymap_order() -> None:
    doc = json.loads(rules.VOCABULARY_FILE.read_text(encoding="utf-8"))
    assert list(VOCABULARY.commands) == [c["id"] for c in doc["commands"]]
    assert load_vocabulary() == VOCABULARY
    assert VOCABULARY.permanent == {"Esc", "Ctrl+K"}
    assert VOCABULARY.reserved["Ctrl+5"] == "browser (switch tab)"
    submit = VOCABULARY.commands["ticket.submit"]
    assert (submit.scope, submit.dangerous, submit.requires_arm, submit.confirm) == (
        "ticket", True, True, True)  # fmt: skip


def _doc(**command: Any) -> dict[str, Any]:
    base = {"id": "a.b", "context": "Chart", "scope": "chart", "focus_contexts": ["Chart"],
            "default": "F", "editable": True, "reserved_override": False, "shadows": [],
            "dangerous": False, "requires_arm": False, "confirm": False}  # fmt: skip
    return {"commands": [base | command], "reserved_keys": {}, "permanent_keys": []}


@pytest.mark.parametrize(
    "doc",
    [
        _doc(editable="yes"),
        _doc(id=1),
        _doc(shadows="x.y"),
        _doc(focus_contexts=[1]),
        {**_doc(), "permanent_keys": "Esc"},
        {**_doc(), "reserved_keys": {"Ctrl+W": 1}},
    ],
)
def test_a_vocabulary_of_the_wrong_types_is_refused(doc: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="wrong type"):
        parse_vocabulary(doc)


def test_a_vocabulary_missing_a_member_is_refused() -> None:
    doc = _doc()
    del doc["commands"][0]["confirm"]
    with pytest.raises(KeyError):
        parse_vocabulary(doc)


def test_a_global_and_a_view_share_a_key_only_as_a_declared_shadow_either_side() -> None:
    g = _command("g.full", "Global", "F11")
    by_view = _vocabulary(g, _command("v.full", "Workspace", "F12", shadows={"g.full"}))
    assert _conflict(by_view, ("v.full", "F11")) is None
    g_says = _command("g.full", "Global", "F11", shadows={"v.full"})
    assert _conflict(_vocabulary(g_says, _command("v.full", "Workspace", "F12")),
                     ("v.full", "F11")) is None  # fmt: skip
    undeclared = _vocabulary(g, _command("v.full", "Workspace", "F12"))
    assert _conflict(undeclared, ("v.full", "F11")) == [
        {"field": "bindings[0].keys", "rule": "binding_conflict",
         "message": "Shares a key with g.full while both can be live."},
        {"field": "bindings", "rule": "binding_conflict",
         "message": "Shares a key with v.full while both can be live."},
    ]  # fmt: skip


def test_a_shadow_never_separates_two_global_commands() -> None:
    vocab = _vocabulary(_command("g.a", "Global", "F2", shadows={"g.b"}),
                        _command("g.b", "Global", "F3", shadows={"g.a"}))  # fmt: skip
    errors = _conflict(vocab, ("g.a", "F3"))
    assert errors is not None and [e["field"] for e in errors] == ["bindings[0].keys", "bindings"]


def test_views_conflict_when_their_focus_contexts_meet() -> None:
    """A command the keymap gives focus contexts has the scope of each (22): it meets a DOM
    command on DOM and none of a Replay one's."""
    wide = _command("c.wide", "Chart", "F4", focus={"Chart", "DOM"})
    vocab = _vocabulary(wide, _command("d.x", "DOM", "F5"), _command("r.x", "Replay", "F6"))
    assert _conflict(vocab, ("c.wide", "F5")) is not None
    assert _conflict(vocab, ("c.wide", "F6")) is None
    assert _conflict(vocab, ("d.x", "F4")) is not None  # the default it keeps is its own key


def test_the_holder_may_be_a_later_entry_only_once_it_was_judged() -> None:
    """An entry loses to a binding the profile keeps or to an earlier entry, never a later one:
    the later entry loses, naming the earlier one's field."""
    vocab = _vocabulary(_command("c.a", "Chart", "F7"), _command("c.b", "Chart", "F8"))
    assert _conflict(vocab, ("c.a", "F9"), ("c.b", "F9")) == [
        {"field": "bindings[1].keys", "rule": "binding_conflict",
         "message": "Shares a key with c.a while both can be live."},
        {"field": "bindings[0].keys", "rule": "binding_conflict",
         "message": "Shares a key with c.b while both can be live."},
    ]  # fmt: skip


def test_an_unbound_entry_or_default_holds_no_key() -> None:
    vocab = _vocabulary(_command("c.a", "Chart", "F7"), _command("c.b", "Chart", "F8"))
    assert _conflict(vocab, ("c.b", ""), ("c.a", "F8")) is None
    assert _conflict(vocab, ("c.a", ""), ("c.b", "")) is None


def test_reserved_and_permanent_keys_name_who_holds_them() -> None:
    vocab = _vocabulary(_command("c.a", "Chart", "F7"))
    for keys, message in (("Ctrl+W", "Ctrl+W is reserved by browser."),
                          ("Esc", "Esc is reserved by the app.")):  # fmt: skip
        with pytest.raises(HotkeyBindingsInvalid) as invalid:
            judge([_entry(vocab, "c.a", keys)], vocab)
        assert invalid.value.errors == [
            {"field": "bindings[0].keys", "rule": "reserved_key", "message": message}
        ]


def test_no_more_than_twenty_items_are_answered() -> None:
    bindings = [_Entry(f"no.such{n}", "F1", "global") for n in range(25)]
    with pytest.raises(HotkeyBindingsInvalid) as invalid:
        judge(bindings)
    assert len(invalid.value.errors) == 20
    assert invalid.value.errors[-1]["field"] == "bindings[19].action"


def test_a_messages_never_echoes_what_the_client_sent() -> None:
    canary = "chart.CANARY<script>"
    bindings = [_Entry(canary, "F1", "global"), _Entry("chart.footprint_toggle", "Ctrl+" + canary,
                                                       "chart")]  # fmt: skip
    with pytest.raises(HotkeyBindingsInvalid) as invalid:
        judge(bindings)
    assert "CANARY" not in json.dumps(invalid.value.errors)


def test_judge_answers_the_stored_map_in_body_order() -> None:
    judged = judge([_Entry("replay.bookmark", "ctrl+b", "replay"),
                    _Entry("chart.footprint_toggle", "", "chart")])  # fmt: skip
    assert list(judged.stored.items()) == [
        ("replay.bookmark", "Ctrl+B"), ("chart.footprint_toggle", "")]  # fmt: skip
    assert judged.rewritten == ()


def test_reads_answer_each_stored_command_in_keymap_order_with_derived_members() -> None:
    stored = {"ticket.submit": "Ctrl+Enter", "no.longer": "F1", "global.palette": "Ctrl+K"}
    assert read_bindings(stored) == [
        {"action": "global.palette", "keys": "Ctrl+K", "scope": "global", "requires_arm": False,
         "confirm": False},
        {"action": "ticket.submit", "keys": "Ctrl+Enter", "scope": "ticket", "requires_arm": True,
         "confirm": True},
    ]  # fmt: skip
    assert read_bindings({}) == []
    vocab = _vocabulary(_command("c.a", "Chart", "F7", arm=True))
    assert read_bindings({"c.a": "F2"}, vocab) == [
        {"action": "c.a", "keys": "F2", "scope": "chart", "requires_arm": True, "confirm": False}
    ]


@pytest.mark.parametrize(
    ("binding", "shape"),
    [("Ctrl", "modifier"), ("Shift", "modifier"), ("Alt+drag", "pointer:drag"),
     ("Shift+wheel", "pointer:wheel"), ("Alt+1..9", "range:1..9"), ("1..4", "range:1..4"),
     ("+", "key"), ("Ctrl++", "key"), ("Ctrl+K", "key"), ("Space", "key")],
)  # fmt: skip
def test_shape_of_names_each_shape(binding: str, shape: str) -> None:
    assert shape_of(binding) == shape


_KEYS = st.sampled_from([
    "a", "Z", "ß", "é", "1", "9", "/", "?", "+", "€", "Esc", "escape", "Del", "space", "Enter",
    "tab", "left", "ArrowUp", "PageDown", "f1", "F12", "F25", "1..9", "4..1", "click", "DRAG",
    "wheel", "ctrl", "Shift", "Banana", "", " ",
])  # fmt: skip
_MODS = st.lists(st.sampled_from(["Ctrl", "ctrl", "Cmd", "Meta", "Alt", "option", "Shift",
                                  "Space", "Hyper"]), max_size=3)  # fmt: skip


@given(mods=_MODS, key=_KEYS, pad=st.sampled_from(["", " ", "\t", chr(0xA0), chr(0xFEFF)]))
def test_a_canonical_binding_is_its_own_canonical_form(mods: list[str], key: str, pad: str) -> None:
    """Idempotent, as the server stores and answers the canonical form: reading back what it stored
    gives the same binding, of the same shape, with at least one atom."""
    found = normalise_binding(pad + "+".join([*mods, key]) + pad)
    if found is not None:
        assert normalise_binding(found) == found
        assert shape_of(found) == shape_of(normalise_binding(found) or "")
        assert rules.binding_atoms(found)
