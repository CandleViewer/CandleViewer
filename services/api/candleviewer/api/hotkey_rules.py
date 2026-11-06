"""The `/settings/hotkeys` rules (E10-T05, #5211): the client's binding grammar and conflict rules,
ported from `apps/web/src/keymap/validate.ts` (with `keymap.ts`'s `bindingAtoms` and
`isSingleLetter` and `registry.ts`'s `contextsOf` and `shadowRationale`), judged against the
generated vocabulary `api/_generated/hotkey_vocabulary.json` (BQ-8: the API image cannot read
`keymap.json`, so the keymap's facts come as data and the rules stay code).

Pure: nothing but the vocabulary is read, once, at import. A JavaScript string operation keeps its
JavaScript meaning here, so the port reads a binding as `validate.ts` does: `trim` and `\\s` take
JavaScript's white space (no U+001C to U+001F or U+0085, but U+FEFF), `\\d` is ASCII, and a key is
upper-cased only when its upper case is one UTF-16 unit (`ß` stays `ß`). `\\p{L}` moves with the
Unicode version, and the browser's is newer than this Python's (15.0 in 3.12): a code point these
tables leave unassigned (`Cn`) may be a letter to the client. A `422` is permanent (BQ-5), so the
port refuses on a code point's category only where its tables know it: Shift stays allowed on a
`Cn` code point (`typedCharacter` refuses a known non-letter) and a dangerous command may be bound
bare to one (`isSingleLetter` answers for a known letter), so no key a client accepts is refused
for it; a client reading the profile back applies its own tables. The shared case fixture
`packages/fixtures/golden/hotkeys/profile_cases.json`, which pytest and vitest both run, pins the
port to the client.

`judge` takes a body's bindings, each already of `HotkeyBinding`'s schema, and answers what a
profile stores and which actions' `requires_arm` or `confirm` it rewrote (BQ-3), or refuses:

- `HotkeyBindingsInvalid` (`422 validation_failed`): one `errors[]` item per refused entry, at most
  20, its rule the first the entry breaks in 22's order: `unknown_action`, `duplicate_action`,
  `scope_mismatch`, `params_not_allowed`, then `keys`' `invalid_keys`, `shape_mismatch`,
  `bare_letter_dangerous`, `reserved_key` and `locked_command` (BQ-2, BQ-4). No acknowledgement is
  checked (CR-305BD-04), and a command the caller cannot run is no refusal (E47-S08's rule, BQ-6).
- `HotkeyBindingConflict` (`409 conflict`, `binding_conflict`): the first pair `checkProfile` would
  report, on the profile filled in with the keymap's defaults. Two commands conflict when they share
  a key (a digit range by each digit) while both can be live; an unbound command conflicts with
  nothing, nor does a view's declared shadow of a Global command (F11). The first item is the entry
  that loses, as the client's import rejects it (to a binding the profile keeps, or to an earlier
  entry), the second the command that keeps the key; each names the other.

No message carries the client's text (C-12.6): only vocabulary ids, defaults and reserved keys.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

VOCABULARY_FILE: Final = Path(__file__).resolve().parent / "_generated" / "hotkey_vocabulary.json"
#: JavaScript's white space (`String.prototype.trim`, `\s`): WhiteSpace and LineTerminator.
JS_SPACE: Final = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009"
    "\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
MODS: Final = ("Ctrl", "Alt", "Shift")
_MOD_ALIASES: Final = {
    "ctrl": "Ctrl", "control": "Ctrl", "cmd": "Ctrl", "command": "Ctrl", "meta": "Ctrl",
    "mod": "Ctrl", "alt": "Alt", "option": "Alt", "shift": "Shift",
}  # fmt: skip
_KEY_ALIASES: Final = {
    "esc": "Esc", "escape": "Esc", "del": "Del", "delete": "Del", "space": "Space",
    "spacebar": "Space", "enter": "Enter", "return": "Enter", "tab": "Tab", "arrowleft": "←",
    "left": "←", "arrowright": "→", "right": "→", "arrowup": "↑", "up": "↑", "arrowdown": "↓",
    "down": "↓", "backspace": "Backspace", "home": "Home", "end": "End", "pageup": "PageUp",
    "pagedown": "PageDown",
}  # fmt: skip
_POINTER: Final = frozenset({"click", "drag", "wheel"})
_ARROWS: Final = frozenset({"←", "→", "↑", "↓"})
_FKEY: Final = re.compile(r"F(?:[1-9]|1[0-9]|2[0-4])")
_RANGE: Final = re.compile(r"([0-9])\.\.([0-9])")
_SPACE_WORD: Final = re.compile(r"space", re.IGNORECASE | re.ASCII)
#: `bindingAtoms`' `/^(.*?)(\d)\.\.(\d)$/`: JavaScript's `.` stops at a line terminator.
_ATOMS: Final = re.compile(r"([^\n\r\u2028\u2029]*?)([0-9])\.\.([0-9])")
_MAX_ERRORS: Final = 20
_LOCKED: Final = "This command cannot be remapped or unbound."


def js_trim(text: str) -> str:
    """`String.prototype.trim`."""
    return text.strip(JS_SPACE)


def _split(raw: str) -> list[str]:
    """`splitBinding`: a trailing `+` is the plus key (`Ctrl++`, `Ctrl+`)."""
    s = js_trim(raw)
    if s == "+":
        return ["+"]
    if s.endswith("++"):
        return [p for p in s[:-2].split("+") if p] + ["+"]
    parts = s.split("+")
    if len(parts) > 1 and parts[-1] == "":
        return [*parts[: -2 if parts[-2] == "" else -1], "+"]
    return parts


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _is_letter(char: str) -> bool:
    """`\\p{L}` for one code point, by this Python's tables."""
    return unicodedata.category(char).startswith("L")


def _unassigned(char: str) -> bool:
    """A code point these tables leave unassigned (`Cn`): the browser's, newer, may call it a
    letter, so the port takes it for neither a letter nor a known non-letter."""
    return unicodedata.category(char) == "Cn"


def _key_name(key: str) -> str | None:
    """`keyName`: a named key, `F1`-`F24`, a digit range, or one character but white space."""
    alias = _KEY_ALIASES.get(key.lower())
    if alias is not None:
        return alias
    upper = key.upper()
    if _FKEY.fullmatch(upper):
        return upper
    if (span := _RANGE.fullmatch(key)) is not None:
        return key if int(span.group(1)) <= int(span.group(2)) else None
    if len(key) != 1 or key in JS_SPACE:
        return None
    return upper if _utf16_length(upper) == 1 else key


def _typed_character(key: str) -> bool:
    """`typedCharacter`: a digit or a punctuation key, alone or as a range, which a press reads as
    the character Shift typed, so Shift never goes on one. An unassigned code point is not one
    (it may be a letter to the client), so Shift stays allowed on it."""
    if _RANGE.fullmatch(key):
        return True
    return len(key) == 1 and not _is_letter(key) and not _unassigned(key) and key not in _ARROWS


def normalise_binding(raw: str) -> str | None:
    """`normaliseBinding`: the canonical `Ctrl+Alt+Shift+Key` of a binding (a pointer gesture may
    take `Space`, a modifier may stand alone), or None outside the grammar."""
    parts = [js_trim(p) for p in _split(raw)]
    last = parts.pop()
    if last == "":
        return None
    alone = _MOD_ALIASES.get(last.lower())
    if not parts and alone is not None:
        return alone
    pointer = last.lower() in _POINTER
    mods: set[str] = set()
    for part in parts:
        mod = _MOD_ALIASES.get(part.lower())
        if mod is None and pointer and _SPACE_WORD.fullmatch(part):
            mod = "Space"
        if mod is None:
            return None
        mods.add(mod)
    key = last.lower() if pointer else _key_name(last)
    if key is None or (not pointer and "Shift" in mods and _typed_character(key)):
        return None
    space = ["Space"] if "Space" in mods else []
    return "+".join([m for m in MODS if m in mods] + space + [key])


def shape_of(binding: str) -> str:
    """`shapeOf`: a key, a digit range, a pointer gesture or a modifier alone."""
    if binding in MODS:
        return "modifier"
    key = _split(binding)[-1]
    if key in _POINTER:
        return f"pointer:{key}"
    return f"range:{key}" if _RANGE.fullmatch(key) else "key"


def binding_atoms(binding: str) -> list[str]:
    """`bindingAtoms`: a range binding's atoms (`Alt+1..9` -> `Alt+1` ... `Alt+9`)."""
    span = _ATOMS.fullmatch(binding)
    if span is None:
        return [binding]
    low, high = int(span.group(2)), int(span.group(3))
    return [f"{span.group(1)}{digit}" for digit in range(low, high + 1)]


def is_single_letter(binding: str) -> bool:
    """`isSingleLetter`: one letter, Shift or not (`Shift+Y` too). An unassigned code point is no
    letter here (it may be one to the client), so a dangerous command may be bound bare to it."""
    rest = binding.removeprefix("Shift+")
    return len(rest) == 1 and _is_letter(rest)


@dataclass(frozen=True, slots=True)
class Command:
    """One keymap command as the vocabulary states it."""

    id: str
    context: str
    scope: str
    focus_contexts: frozenset[str]
    default: str
    editable: bool
    reserved_override: bool
    shadows: frozenset[str]
    dangerous: bool
    requires_arm: bool
    confirm: bool


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """The keymap's commands in its order, the reserved keys expanded (each with what reserves it)
    and the keys the locked commands keep for themselves (`validate.ts`'s `PERMANENT`)."""

    commands: Mapping[str, Command]
    reserved: Mapping[str, str]
    permanent: frozenset[str]


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("the hotkey vocabulary holds a value of the wrong type")
    return value


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("the hotkey vocabulary holds a value of the wrong type")
    return value


def _texts(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        raise ValueError("the hotkey vocabulary holds a value of the wrong type")
    return frozenset(_text(item) for item in value)


def _command(c: Mapping[str, Any]) -> Command:
    return Command(
        _text(c["id"]), _text(c["context"]), _text(c["scope"]), _texts(c["focus_contexts"]),
        _text(c["default"]), _flag(c["editable"]), _flag(c["reserved_override"]),
        _texts(c["shadows"]), _flag(c["dangerous"]), _flag(c["requires_arm"]),
        _flag(c["confirm"]),
    )  # fmt: skip


def parse_vocabulary(doc: Mapping[str, Any]) -> Vocabulary:
    """The vocabulary a document states; `ValueError` or `KeyError` when it is malformed, so the
    API fails at import rather than judging a profile by a broken keymap."""
    commands = {command.id: command for command in map(_command, doc["commands"])}
    reserved = {_text(key): _text(why) for key, why in doc["reserved_keys"].items()}
    return Vocabulary(commands, reserved, _texts(doc["permanent_keys"]))


def load_vocabulary(path: Path = VOCABULARY_FILE) -> Vocabulary:
    return parse_vocabulary(json.loads(path.read_text(encoding="utf-8")))


VOCABULARY: Final = load_vocabulary()


class BindingIn(Protocol):
    """One entry of a body's `bindings`, already of `HotkeyBinding`'s schema."""

    @property
    def action(self) -> str: ...

    @property
    def keys(self) -> str: ...

    @property
    def scope(self) -> str: ...

    @property
    def requires_arm(self) -> bool | None: ...

    @property
    def confirm(self) -> bool | None: ...

    @property
    def params(self) -> Mapping[str, Any] | None: ...


class HotkeyBindingsInvalid(Exception):
    """`422 validation_failed`: `errors` holds at most 20 items, each `field`, `rule`, `message`."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("the profile's bindings are invalid")
        self.errors = errors


class HotkeyBindingConflict(Exception):
    """`409 conflict`, rule `binding_conflict`: `errors` holds one item for each of the pair."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("two bindings share a key while both can be live")
        self.errors = errors


@dataclass(frozen=True, slots=True)
class Judged:
    """What a profile stores (action -> canonical binding, `""` unbound) and the actions whose
    `requires_arm` or `confirm` the body sent otherwise than the server derives (BQ-3), each
    once, in the body's order: `Hotkey-Bindings-Rewritten`."""

    stored: dict[str, str]
    rewritten: tuple[str, ...]


def _keys_rule(cmd: Command, raw: str, vocab: Vocabulary) -> tuple[str, str] | str:
    """The canonical binding, or `(rule, message)` for the first `keys` rule it breaks (22's
    order; `validate.ts`'s `entryProblem` and `ownProblem`, `invalid-binding` split in two)."""
    if js_trim(raw) == "":  # unbinding: any command but a locked one (WCAG 2.1.4)
        return ("locked_command", _LOCKED) if not cmd.editable else ""
    binding = normalise_binding(raw)
    if binding is None:
        return "invalid_keys", "Not a key binding: see HotkeyBinding.keys for its grammar."
    if shape_of(binding) != shape_of(cmd.default):
        return "shape_mismatch", f"A binding of this command keeps the shape of {cmd.default}."
    if cmd.dangerous and is_single_letter(binding):
        return "bare_letter_dangerous", (
            "This command needs Ctrl or Alt with a letter: the letter alone could run it."
        )
    own = binding == cmd.default
    for atom in binding_atoms(binding):
        kept = atom in vocab.permanent
        # A command holding its reviewed default keeps it: a locked one its reserved key, an
        # override its OS key.
        reviewed = own and (not cmd.editable if kept else cmd.reserved_override)
        if (kept or atom in vocab.reserved) and not reviewed:
            by = "the app" if kept else vocab.reserved[atom]
            return "reserved_key", f"{atom} is reserved by {by}."
    if not cmd.editable and not own:
        return "locked_command", _LOCKED
    return binding


def _error(index: int, member: str, rule: str, message: str) -> dict[str, str]:
    return {"field": f"bindings[{index}].{member}", "rule": rule, "message": message}


def _entry(
    index: int, entry: BindingIn, cmd: Command | None, repeated: bool, vocab: Vocabulary
) -> dict[str, str] | str:
    """The entry's canonical binding, or the `errors[]` item of the first rule it breaks."""
    if cmd is None:
        return _error(index, "action", "unknown_action", "Not a command of the keymap.")
    if repeated:
        return _error(index, "action", "duplicate_action", "An earlier entry binds this command.")
    if entry.scope != cmd.scope:
        return _error(index, "scope", "scope_mismatch", f"This command's scope is {cmd.scope}.")
    if entry.params:
        message = "No command takes parameters yet: leave params out or send {}."
        return _error(index, "params", "params_not_allowed", message)
    found = _keys_rule(cmd, entry.keys, vocab)
    return found if isinstance(found, str) else _error(index, "keys", *found)


def _exclusive(a: Command, b: Command) -> bool:
    """`exclusive`: never live at once. Global is the wildcard: a Global and a view command are
    exclusive only as a declared shadow, two Global commands never; views are exclusive when
    their focus contexts are disjoint."""
    a_global, b_global = "Global" in a.focus_contexts, "Global" in b.focus_contexts
    if a_global or b_global:
        return a_global != b_global and (b.id in a.shadows or a.id in b.shadows)
    return a.focus_contexts.isdisjoint(b.focus_contexts)


def _conflict(
    entries: Sequence[tuple[int, Command, str]], vocab: Vocabulary
) -> tuple[tuple[int, Command], tuple[int | None, Command]] | None:
    """`checkProfile`'s first loser on the profile filled in with the defaults: the first entry, in
    body order, sharing a key with a command `conflictsWith` names (in keymap order) that the
    profile keeps or an earlier entry holds; and that command, with its entry's index, if any."""
    held = {c.id: c.default for c in vocab.commands.values()}
    held.update((cmd.id, binding) for _, cmd, binding in entries)
    order = {cmd.id: at for at, (_, cmd, _) in enumerate(entries)}
    where = {cmd.id: index for index, cmd, _ in entries}
    for at, (index, cmd, binding) in enumerate(entries):
        if binding == "":
            continue
        atoms = set(binding_atoms(binding))
        for other in vocab.commands.values():
            theirs = held[other.id]
            if other.id == cmd.id or theirs == "" or atoms.isdisjoint(binding_atoms(theirs)):
                continue
            if not _exclusive(cmd, other) and order.get(other.id, -1) < at:
                return (index, cmd), (where.get(other.id), other)
    return None


def _rewrites(entry: BindingIn, cmd: Command) -> bool:
    """A value the body sent for `requires_arm` or `confirm` that is not the derived one (BQ-3)."""
    arm, confirm = entry.requires_arm, entry.confirm
    return (arm is not None and arm != cmd.requires_arm) or (
        confirm is not None and confirm != cmd.confirm
    )


def judge(bindings: Sequence[BindingIn], vocabulary: Vocabulary | None = None) -> Judged:
    """The profile `bindings` make, or its refusal (see the module docstring)."""
    vocab = VOCABULARY if vocabulary is None else vocabulary
    errors: list[dict[str, str]] = []
    entries: list[tuple[int, Command, str]] = []
    seen: set[str] = set()
    for index, entry in enumerate(bindings):
        cmd = vocab.commands.get(entry.action)
        found = _entry(index, entry, cmd, entry.action in seen, vocab)
        seen.add(entry.action)
        if isinstance(found, dict):
            errors.append(found)
        elif cmd is not None:
            entries.append((index, cmd, found))
    if errors:
        raise HotkeyBindingsInvalid(errors[:_MAX_ERRORS])
    if (pair := _conflict(entries, vocab)) is not None:
        (index, loser), (held_at, holder) = pair
        field = "bindings" if held_at is None else f"bindings[{held_at}].keys"
        message = "Shares a key with {} while both can be live."
        raise HotkeyBindingConflict([
            {"field": f"bindings[{index}].keys", "rule": "binding_conflict",
             "message": message.format(holder.id)},
            {"field": field, "rule": "binding_conflict", "message": message.format(loser.id)},
        ])  # fmt: skip
    rewritten = tuple(bindings[index].action for index, cmd, _ in entries
                      if _rewrites(bindings[index], cmd))  # fmt: skip
    return Judged({cmd.id: binding for _, cmd, binding in entries}, rewritten)


def read_bindings(
    stored: Mapping[str, str], vocabulary: Vocabulary | None = None
) -> list[dict[str, object]]:
    """22 `HotkeyProfile.bindings` of a stored profile: one entry per stored command, in the
    keymap's order, with the `scope`, `requires_arm` and `confirm` derived from its action; an id
    the keymap no longer has is left out (BQ-2). `params` is never answered."""
    vocab = VOCABULARY if vocabulary is None else vocabulary
    return [
        {"action": c.id, "keys": stored[c.id], "scope": c.scope, "requires_arm": c.requires_arm,
         "confirm": c.confirm}
        for c in vocab.commands.values() if c.id in stored
    ]  # fmt: skip


__all__ = [
    "JS_SPACE", "MODS", "VOCABULARY", "VOCABULARY_FILE", "BindingIn", "Command",
    "HotkeyBindingConflict", "HotkeyBindingsInvalid", "Judged", "Vocabulary", "binding_atoms",
    "is_single_letter", "js_trim", "judge", "load_vocabulary", "normalise_binding",
    "parse_vocabulary", "read_bindings", "shape_of",
]  # fmt: skip
