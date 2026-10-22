"""Contract (E29-T07 #915, E34-S03 #1111): only the owner can loosen a position's stop.

`24-internal-schemas.md` section 8.8 rule 5 makes the loosening override the owner's alone, on
`setPositionTpSl` under a live `risk_caps` step-up, audited before it is sent (`sl.loosened`).
Any other role's loosening is refused and audited (`sl.loosen_refused`); `amendOrder` and
`amendTradeGroup` refuse a looser stop outright; the check sits once, at the recorded-stop writer
(C-2.21), and never refuses a tightening (C-2.6). No route here is mounted yet: E29-T07 and
E34-S03 implement them against this text (C-6.1). Read from the spec and the plan, never from a
copy (AGENTS.md section 6 rule 12).
"""

from __future__ import annotations

from typing import Any

from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_OPS: dict[str, Any] = {
    op["operationId"]: op
    for item in _SPEC["paths"].values()
    for op in item.values()
    if isinstance(op, dict) and "operationId" in op
}
_CODES: dict[str, Any] = {entry["code"]: entry for entry in _SPEC["x-error-codes"]}
_INTERNAL_DOC = (OPENAPI_SPEC_PATH.parent / "24-internal-schemas.md").read_text(encoding="utf-8")


def _words(text: str) -> str:
    """A text on one line: a YAML block or a Markdown list keeps its line breaks."""
    return " ".join(text.split())


def _rule_5() -> str:
    """24 section 8.8 rule 5, from its number to rule 6."""
    section = _INTERNAL_DOC.split("\n### 8.8 ", 1)[1].split("\n### 8.9 ", 1)[0]
    return _words(section.split("\n5. ", 1)[1].split("\n6. ", 1)[0])


def _step_up_classes() -> set[str]:
    body = _OPS["authStepUp"]["requestBody"]["content"]["application/json"]["schema"]
    return set(body["properties"]["action_class"]["enum"])


def test_rule_5_gives_the_loosening_override_to_the_owner_alone() -> None:
    rule = _rule_5()
    for phrase in (
        "unless the **owner** explicitly overrides. The override is the owner's alone: one "
        "confirmation dialog, then `setPositionTpSl` under a live `risk_caps` step-up, the "
        "loosening audited write-ahead (`sl.loosened`)",
        "No other role has it and no other request carries it",
        "another role's loosening on `setPositionTpSl` is refused with `403 risk_limit_breached` "
        "before any send, its refusal audited write-ahead (`sl.loosen_refused`, with the actor, "
        "role, account, and the stop before and after)",
        "the owner's without the step-up answers `403 step_up_required` "
        "(`action_class: risk_caps`)",
        "`amendOrder` and `amendTradeGroup` refuse a looser stop outright",
        "so the override exists on `setPositionTpSl` alone",
        "a rule action never loosens a stop: a trail or breakeven (§10.7) only ever tightens",
        "and a rule action that would widen one (§11.6: `modify_stop_loss` with "
        "`only_tighten=false`, or `widen_stop`) is refused at the writer like any other "
        "loosening, whatever permission the rule holds",
    ):
        assert phrase in rule, phrase


def test_rule_5_puts_one_synchronous_check_at_the_recorded_stop_writer() -> None:
    rule = _rule_5()
    for phrase in (
        "its trigger is further from the market on the position's side (lower for a long, higher "
        "for a short)",
        "in Partial mode, its size covers less than the lesser of the record's size and the "
        "position's size at the write, so a position that shrank",
        "for a native trail, its distance is greater, or the trigger it would set",
        "The check is synchronous (C-2.21) and sits once, at the recorded-stop writer (rule 6)",
        "every stop request, from every writer, is compared with the record in force before its "
        "own record is written",
        "so before B8's `LOOSEN_SL` and before any send",
        "No route or rule keeps a copy of the check",
        "A tightening is never refused by it (§8.10, C-2.6), and neither is attaching a stop where "
        "the exchange shows none",
    ):
        assert phrase in rule, phrase


def test_a_rule_action_that_widens_a_stop_is_refused_at_the_writer() -> None:
    """Section 11.6's vocabulary no longer lets a rule permission loosen a stop."""
    section = _INTERNAL_DOC.split("\n### 11.6 ", 1)[1].split("\n### 11.7 ", 1)[0]
    row = next(line for line in section.splitlines() if line.startswith("| `modify_stop_loss`"))
    assert "`only_tighten=false` is refused at the writer (§8.8 rule 5)" in row
    assert "rules.loosen_stop" not in row


def test_both_loosening_actions_are_in_the_closed_audit_vocabulary() -> None:
    section = _INTERNAL_DOC.split("\n### 15.5 ", 1)[1].split("\n### 15.6 ", 1)[0]
    vocabulary = section.split("\n\n", 2)[1]
    assert "`sl.loosened`, `sl.loosen_refused`, `tp.modified`" in vocabulary
    text = _words(section)
    assert "Both are written ahead, the loosening before its request leaves and the refusal " in (
        text
    )
    assert (
        "with the actor, role and account, the position as the object, and the stop before and "
        "after (trigger price, and the size in Partial mode). A refusal is outcome `denied`."
    ) in text
    assert "`amendOrder` and `amendTradeGroup` refuse a looser stop as their own" in text


def test_set_position_tp_sl_lets_only_the_owner_loosen_under_a_step_up() -> None:
    op = _OPS["setPositionTpSl"]
    text = _words(op["description"])
    for phrase in (
        "**Only the owner can loosen a stop** (24-internal-schemas.md section 8.8 rule 5)",
        "needs the owner's role and a live `risk_caps` step-up",
        "the owner without one gets `403 step_up_required` (`action_class: risk_caps`)",
        "and any other role `403 risk_limit_breached`, its refusal audited "
        "(`sl.loosen_refused`), with nothing sent",
        "The owner's loosening is audited before it is sent (`sl.loosened`)",
        "or a wider `trailing_stop`",
        "a tightening is never refused by it (C-2.6)",
    ):
        assert phrase in text, phrase
    assert "risk_caps" in _step_up_classes()
    assert op["responses"]["403"] == {"$ref": "#/components/responses/Forbidden"}
    for code in ("step_up_required", "risk_limit_breached"):
        assert _CODES[code]["status"] == 403, code


def test_amend_order_refuses_a_looser_stop_whatever_the_role() -> None:
    op = _OPS["amendOrder"]
    text = _words(op["description"])
    for phrase in (
        "A `stop_loss` moved to loosen it on an entry is refused with `403 risk_limit_breached`, "
        "whatever the caller's role, before any send",
        "a long entry's stop may only rise and a short entry's only fall, before the fill and "
        "after it",
        "The one way to loosen a stop is the owner's override on `setPositionTpSl`",
        "A tightening is never refused by this check (C-2.6; section 8.10)",
    ):
        assert phrase in text, phrase
    assert op["responses"]["403"] == {"$ref": "#/components/responses/Forbidden"}
