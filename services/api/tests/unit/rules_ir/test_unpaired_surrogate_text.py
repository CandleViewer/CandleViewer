"""Rule IR text with a lone UTF-16 surrogate is a typed refusal, never a ``UnicodeEncodeError``.

JSON writes one as an escape (``"\\ud800"``) and ``json.loads`` makes it a ``str`` with no UTF-8
form. The IR's unconstrained text (an ``Action.params`` key or value, a list in them, a
``MetricRef`` string param or key) reaches the hash: ``canonicalize`` refuses it with an
``IrValueError`` naming the path, which the routes answer as ``422 rule_ir_invalid`` (#4172). A key
is named with the code point escaped, so the path prints as UTF-8. A paired emoji is one code point
and hashes as it did on the base commit.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.rules.ir import Rule, canonical, canonicalize, ir_hash

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "rule_ir"
_BASE: dict[str, Any] = json.loads((FIXTURES / "form_simple_0.json").read_text(encoding="utf-8"))
REASON = "Text holds an unpaired surrogate code point"
#: ``ir_hash(_doc("\U0001f600", *WHERE))``, computed on the base commit: an emoji hashes alike.
EMOJI = "4fdf42ca0b8b334ac73e8c7bc4ce2c71adb2c17ea13c4c6229cd34880d4ce202"
WHERE = (
    "action param key", "action param value", "nested list item", "metric param key",
    "metric param value",
)  # fmt: skip
#: Each alone, with the escaped form a refused key is named by: a high surrogate, a low one, and a
#: low before a high (two lone ones, not a pair).
LONE = {
    "high": ("\ud800", "\\ud800"), "low": ("\udc00", "\\udc00"),
    "low-high": ("\udc00\ud800", "\\udc00\\ud800"),
}  # fmt: skip


def _doc(text: str, *where: str) -> dict[str, Any]:
    """``form_simple_0`` with ``text`` at each place named in ``where``."""
    doc = copy.deepcopy(_BASE)
    act: dict[str, Any] = {"channel": "ui", "severity": "info", "template": "x"}
    metric: dict[str, Any] = {"n": 14}
    for place in where:
        if place == "action param key":
            act[text] = "x"
        elif place == "action param value":
            act["note"] = text
        elif place == "nested list item":
            act["tags"] = ["a", ["b", text]]
        elif place == "metric param key":
            metric[text] = 1
        else:
            metric["source"] = text
    doc["conditions"]["left"]["params"] = metric
    doc["actions"][0]["params"] = act
    return doc


def _path(where: str, escaped: str) -> tuple[str | int, ...]:
    return {
        "action param key": ("actions", 0, "params", escaped),
        "action param value": ("actions", 0, "params", "note"),
        "nested list item": ("actions", 0, "params", "tags", 1, 1),
        "metric param key": ("conditions", "left", "params", escaped),
        "metric param value": ("conditions", "left", "params", "source"),
    }[where]


@pytest.mark.parametrize("lone", sorted(LONE))
@pytest.mark.parametrize("where", WHERE)
def test_canonicalize_lone_surrogate_in_ir_text_is_a_refusal_naming_its_path(
    where: str, lone: str
) -> None:
    text, escaped = LONE[lone]
    rule = Rule.model_validate(_doc(text, where))  # unconstrained text: the model takes it
    for hashing in (canonicalize, ir_hash):
        with pytest.raises(canonical.IrValueError) as caught:
            hashing(rule)
        assert (caught.value.loc, caught.value.reason) == (_path(where, escaped), REASON)


@pytest.mark.parametrize("where", ["metric param key", "metric param value"])
def test_condition_hash_lone_surrogate_in_metric_param_is_a_refusal_naming_its_path(
    where: str,
) -> None:
    rule = Rule.model_validate(_doc("\udfff", where))
    with pytest.raises(canonical.IrValueError) as caught:
        canonical.condition_hash(rule.model_dump())
    assert (caught.value.loc, caught.value.reason) == (_path(where, "\\udfff"), REASON)


def test_ir_value_error_for_a_lone_surrogate_key_prints_as_utf8() -> None:
    """The message a 422 carries holds the escape, never the code point itself."""
    with pytest.raises(canonical.IrValueError) as caught:
        canonicalize(_doc("k\ud800", "action param key"))
    assert str(caught.value) == f"{REASON} at /actions/0/params/k\\ud800"


def test_ir_hash_paired_emoji_hashes_to_its_pinned_base_value() -> None:
    """U+1F600 is one code point; JSON sends it as the escaped pair ``\\ud83d\\ude00``."""
    doc = _doc("\U0001f600", *WHERE)
    sent = json.dumps(doc)  # ensure_ascii: the emoji goes as its escaped surrogate pair
    assert "\\ud83d\\ude00" in sent
    assert ir_hash(doc) == ir_hash(json.loads(sent)) == EMOJI
    assert "\U0001f600".encode() in canonicalize(doc)


@pytest.mark.parametrize("hashing", ["canonicalize", "ir_hash", "condition_hash"])
def test_hash_encode_backstop_answers_ir_value_error_never_unicode_encode_error(
    monkeypatch: pytest.MonkeyPatch, hashing: str
) -> None:
    """Whatever text reaches the final ``.encode()``, its failure is the typed refusal."""
    rule = Rule.model_validate(_doc("ok", *WHERE))
    monkeypatch.setattr(canonical, "_normalise", lambda _view: {"note": "\ud800"})
    run = {
        "canonicalize": lambda: canonicalize(rule), "ir_hash": lambda: ir_hash(rule),
        "condition_hash": lambda: canonical.condition_hash(rule.model_dump()),
    }[hashing]  # fmt: skip
    with pytest.raises(canonical.IrValueError) as caught:
        run()
    assert (caught.value.loc, caught.value.reason) == ((), REASON)


_CHAR = st.characters(exclude_categories=()) | st.characters(categories=["Cs"])
_TEXT = st.lists(_CHAR, max_size=6).map("".join)  # st.text() merges the two, drawing few Cs


@settings(max_examples=300, deadline=None, database=None)
@given(_TEXT)
def test_canonicalize_any_drawn_text_hashes_or_is_refused_never_unicode_encode_error(
    text: str,
) -> None:
    """Text drawn with surrogates, in every place: refused exactly when it holds one."""
    rule = Rule.model_validate(_doc(text, *WHERE))
    lone = any(0xD800 <= ord(c) <= 0xDFFF for c in text)
    try:
        canonicalize(rule)
    except canonical.IrValueError as exc:
        assert lone and exc.reason == REASON, exc
    else:
        assert not lone
