"""Contract (E29-T07 #915, E34-S03 #1111): only the owner can loosen a position's stop.

`24-internal-schemas.md` section 8.8 rule 5 makes the loosening override the owner's alone, on
`setPositionTpSl` under a live `sl_loosen` step-up, audited before it is sent (`sl.loosened`).
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
        "confirmation dialog, then `setPositionTpSl` under a live `sl_loosen` step-up, a no-grace "
        "class (one fresh code per loosening, bound to that exact request, §15.3), the loosening "
        "audited write-ahead (`sl.loosened`)",
        "No other role has it and no other request carries it",
        "another role's loosening on `setPositionTpSl` is refused with `403 risk_limit_breached` "
        "before any send, its refusal audited write-ahead (`sl.loosen_refused`, with the actor, "
        "role, account, and the stop before and after)",
        "the owner's without the step-up answers `403 step_up_required` "
        "(`action_class: sl_loosen`)",
        "`amendOrder` and `amendTradeGroup` refuse a looser stop outright",
        "so the override exists on `setPositionTpSl` alone",
        "a rule action never loosens a stop: a trail or breakeven (§10.7) only ever tightens",
        "and a rule action that would widen one (§11.6: `modify_stop_loss` with "
        "`only_tighten=false`, or `widen_stop`) is refused at the writer like any other "
        "loosening, whatever permission the rule holds, its refusal audited (`sl.loosen_refused`, "
        "§15.5)",
    ):
        assert phrase in rule, phrase


def test_rule_5_puts_one_synchronous_check_at_the_recorded_stop_writer() -> None:
    rule = _rule_5()
    for phrase in (
        "its trigger is further from the market on the position's side (lower for a long, higher "
        "for a short)",
        "A stop is looser than the record in force when:",
        "its cover is smaller: a Full-mode stop covers the whole position and a Partial-mode one "
        "its size, and a request's cover is looser when it is less than the lesser of the "
        "record's cover and the position's size at the write",
        "compared with the record's native trail: it clears that trail, its distance is greater, "
        "or it arms later (a higher activation price for a long, a lower one for a short; a trail "
        "with no activation price arms at once)",
        "Otherwise adding a trail where the record has none never loosens.",
        "A request that omits the trail leaves the venue's trail in place, and its record carries "
        "the record's trail forward (rule 6), so only an explicit clear (`trailing_stop: null`) "
        "removes one",
        "the writer refuses a clear before any record or audit is written, the owner's included",
        "is compared by the trigger it re-arms at, against the trigger in force",
        "where a record is in force it attaches that recorded stop, audited as `sl.attached` with "
        "the reason `record_in_force`",
        "The check is synchronous (C-2.21) and sits once, at the recorded-stop writer (rule 6)",
        "every stop request, from every writer, is compared with the record in force before its "
        "own record is written",
        "so before B8's `LOOSEN_SL` and before any send",
        "No route or rule keeps a copy of the check",
        "A tightening is never refused by it (§8.10, C-2.6). The missing-stop attach is the one "
        "exception: rule 3's watchdog and rule 4's attach of a missing stop (§8.5 step 5)",
        "against its `sl_trigger_by` price (the mark price by default)",
        "B8's `attach_fallback_sl` sends that stop, the recorded one first",
        "with `400 validation_failed` (rule `trail_clear_unsupported`), a refusal of the request's "
        "shape that writes no `sl.*` record",
        "attached only where no record is in force or the market is already through the recorded "
        "trigger",
        "No other writer's request is exempt, and the writer takes no stop terms from a caller for "
        "it: it derives the exempt stop from its own latest read",
        "audited as `sl.attached` with the reason `no_record_in_force` or `trigger_passed`",
    ):
        assert phrase in rule, phrase
    assert "neither is attaching a stop where the exchange shows none" not in rule  # D-4137-02
    assert "compared only with the record's native trail" not in rule  # F-4137-02


def test_under_a_recorded_trail_the_trigger_in_force_is_the_trailed_stop() -> None:
    """F-4137-01: the venue moves a trailed stop while the record keeps its arm-time trigger, so a
    request that is tighter than the record but looser than the trailed stop is a loosening."""
    rule = _rule_5()
    for phrase in (
        "its trigger is further from the market on the position's side (lower for a long, higher "
        "for a short) than the trigger in force: the record's or, under a native trail the record "
        "holds, the tighter of the record's and the stop the position reports in the writer's own "
        "read, as the venue moves a trailed stop with the price (§10.7) while the record keeps the "
        "trigger it was written with",
        "changed or re-sent, is compared by the trigger it re-arms at, against the trigger in "
        "force",
    ):
        assert phrase in rule, phrase
    text = _words(_OPS["setPositionTpSl"]["description"])
    assert (
        "than the trigger in force, which under a recorded trail is the tighter of the record's "
        "and the stop the position reports"
    ) in text


def test_a_trail_that_arms_beyond_the_trigger_in_force_is_looser_until_o4_answers() -> None:
    """F-4137-02: whether the venue keeps the fixed stop beside an active trail is open (`[O-4]`),
    so until E29-K01 answers, a trail that arms further from the market than the trigger in force
    is looser, added or changed."""
    rule = _rule_5()
    assert (
        "`[O-4]`: whether the venue keeps the fixed stop in force beside an active trail is open "
        "(E29-K01); until it is confirmed, a trail that arms at the write or later, one added "
        "where the record has none or a change to a recorded trail the market has not yet armed, "
        "is looser too where the level it arms at is further from the market than the trigger in "
        "force: its activation price (for a trail with none, the `sl_trigger_by` price of the "
        "writer's own read) less its distance for a long, plus it for a short."
    ) in rule
    assert "a trail, added or changed, is looser too" not in rule  # F2-4137-02
    text = _words(_OPS["setPositionTpSl"]["description"])
    assert (
        "until the venue's behaviour is confirmed, one not yet armed that arms further from the "
        "market than that trigger, or an armed one that re-arms there"
    ) in text


def test_an_armed_trail_goes_by_the_trigger_it_re_arms_at_so_a_tighter_one_passes() -> None:
    """F2-4137-02: the interim `[O-4]` clause would read a tighter distance on an armed trail as
    looser (its activation price lies behind the trailed stop), refusing a tightening (C-2.6), so
    an armed trail, changed or re-sent, is compared by the trigger it re-arms at."""
    assert (
        "until it is confirmed, an armed trail (the record's, once the market has passed its "
        "activation price, or one recorded at once), changed or re-sent, is compared by the "
        "trigger it re-arms at, against the trigger in force, not by the level a trail not yet "
        "armed is checked at; its activation price stays as recorded or arms earlier (lower for a "
        "long, higher for a short), as a later one is looser (above). So a tighter distance on an "
        "armed trail is no loosening where it re-arms no further from the market than the "
        "trigger in force"
    ) in _rule_5()
    assert "never by its activation price" not in _rule_5()  # F3-4137-01


def test_a_trail_with_no_activation_price_is_recorded_with_the_writers_one() -> None:
    """F-4137-04: `rs_trail` holds both of a trail's numbers or neither, so the writer records a
    trail sent with none at the `sl_trigger_by` price of its own read."""
    section = _INTERNAL_DOC.split("\n### 8.8 ", 1)[1].split("\n### 8.9 ", 1)[0]
    rule_6 = _words(section.split("\n6. ", 1)[1])
    assert (
        "a trail sent with no activation price arms at once, and its record takes as its "
        "activation price the `sl_trigger_by` price of the writer's own read at the write, so a "
        "recorded trail always holds both numbers, `21-database-schema.md` §3.3.11 `rs_trail`"
    ) in rule_6
    schema = _SPEC["components"]["schemas"]["SetTpSlRequest"]["properties"]["activation_price"]
    assert "Omitted, it arms at once, and its record takes the `sl_trigger_by` price" in (
        _words(schema["description"])
    )


def test_the_owners_step_up_is_the_no_grace_sl_loosen_class() -> None:
    """F-4137-03: the owner's default (#2701) is a no-grace class, one loosening per step-up; the
    contract declares `sl_loosen` ahead of the service (C-6.1)."""
    assert "sl_loosen" in _step_up_classes() and "risk_caps" in _step_up_classes()
    step_up = _OPS["authStepUp"]
    assert "`live_enablement`, `killswitch`, `backups` and `sl_loosen` are no-grace" in _words(
        step_up["description"]
    )
    body = step_up["requestBody"]["content"]["application/json"]["schema"]
    klass = _words(body["properties"]["action_class"]["description"])
    assert (
        "`sl_loosen` gates the owner's loosening of a position's stop (`setPositionTpSl`" in klass
    )
    assert "`live_enablement`/`killswitch`/`backups`/`sl_loosen`: none, fresh code each time" in (
        _INTERNAL_DOC
    )
    assert "the owner's loosening of a position's stop (`sl_loosen`, §8.8 rule 5)" in _INTERNAL_DOC
    for text in (_rule_5(), _words(_OPS["setPositionTpSl"]["description"])):
        assert "risk_caps" not in text


def test_the_watchdog_attaches_the_record_in_force_where_it_can() -> None:
    """Rule 3 (D-4137-02): over a record in force the watchdog sends that recorded stop, as step 5
    would, and its profile fallback only where none is in force or none can be placed."""
    section = _INTERNAL_DOC.split("\n### 8.8 ", 1)[1].split("\n### 8.9 ", 1)[0]
    rule = _words(section.split("\n3. ", 1)[1].split("\n4. ", 1)[0])
    for phrase in (
        "Where a record is in force for the position (rule 6) and its trigger can still be placed "
        "(the market is not already through it: below it for a long, above it for a short)",
        "the watchdog attaches that recorded stop, as §8.5 step 5 would; otherwise it attaches a "
        "fallback SL at `profile.fallback_sl_offset`",
        "through B8's fallback path (`attach_fallback_sl`; INV-B8-d, INV-B8-f)",
    ):
        assert phrase in rule, phrase
    five = _rule_5()
    assert "That fallback is B8's path, never a free choice: bounded by `CV_B8_MAX_FALLBACK`" in (
        five
    )
    assert "so a loosening by necessity is visible, never silent" in five


def test_a_group_amend_never_clears_a_trail() -> None:
    """D3-4137-01: `amendTradeGroup`'s body refuses a trail clear as `setPositionTpSl` does."""
    request = _words(_SPEC["components"]["schemas"]["AmendTradeGroupRequest"]["description"])
    assert (
        "`trailing_stop: null` over a trail is refused with `400 validation_failed` (rule "
        "`trail_clear_unsupported`"
    ) in request
    assert "`null` clears `take_profit` or `trailing_stop`" not in request


def test_the_gate_and_the_arm_token_refuse_a_looser_amend_outright() -> None:
    """F-4137-06: §8.10 and `ArmToken` no longer offer a loosened stop on the two amends, which
    rule 5 refuses outright; the E35 follow-up names 22's `widen_stop` and `loosens_risk` texts."""
    gate = _words(_INTERNAL_DOC)
    assert (
        "Risk-increasing amends (quantity up, trigger re-armed, and the owner's loosened stop on "
        "`setPositionTpSl`, the one loosening §8.8 rule 5 allows; `amendOrder` and "
        "`amendTradeGroup` refuse a looser stop outright) are refused the same way."
    ) in gate
    arm = _words(_SPEC["components"]["parameters"]["ArmToken"]["description"])
    assert "(quantity up, trigger re-armed) on `amendOrder`, `amendTradeGroup` or" in arm
    assert "stop loosened" not in arm
    follow_up = _words(_INTERNAL_DOC.split("\n### 19.26 ", 1)[1])
    assert '`22-api-openapi.yaml`\'s `widen_stop` text ("an owner with an elevated session")' in (
        follow_up
    )
    assert '`loosens_risk` ("gate them behind the owner-only permission")' in follow_up


def test_the_other_texts_follow_rule_5() -> None:
    """D3-4137-04/-06: section 10.7, rule 6, the restore's cap, the rule table and step 5's code."""
    doc = _words(_INTERNAL_DOC)
    for phrase in (
        "re-issues it as the price moves, never wider than the trail in force (§8.8 rule 5)",
        "and whether a re-sent armed trail is re-based at the market) are the E29 threat model's "
        "open input O-4",
        "the nearer trigger with the larger size (at most the position's)",
        "| No native SL >10 s → attach the recorded stop, else the fallback (§8.8 rule 3) + "
        "critical alert |",
    ):
        assert phrase in doc, phrase
    step_5 = _INTERNAL_DOC.split("\n### 8.5 ", 1)[1].split("\n### 8.6 ", 1)[0]
    assert "await oms.attach_missing_sl(p)" in step_5
    assert "tighter(cur, rec, p) and not rec.trail_moved(p)" in step_5  # looser()'s twin
    assert "tighter(cur, rec, p.side)" not in step_5
    assert "which only the owner's override does (§8.8 rule 5)" in _words(step_5)
    assert "rule 5's audited confirmation" not in step_5
    assert "looser(cur, rec, p)" in step_5
    assert 'attach_protective_sl(p, rec, reason="reconcile_missing_sl")' not in step_5


def test_step_5_and_the_rule_table_defer_to_rule_3() -> None:
    """D2-4137-01: no other text says the watchdog never sends the recorded stop."""
    assert "attaches a fallback at `profile.fallback_sl_offset`, not the recorded stop" not in (
        _INTERNAL_DOC
    )
    assert "| Position without a native SL >10 s → attach fallback" not in _INTERNAL_DOC
    step_5 = _words(_INTERNAL_DOC.split("\n### 8.5 ", 1)[1].split("\n### 8.6 ", 1)[0])
    assert (
        "attaches the record in force where its trigger can still be placed, its profile "
        "fallback otherwise (§8.8 rules 3 and 5)"
    ) in step_5
    section = _INTERNAL_DOC.split("\n### 15.5 ", 1)[1].split("\n### 15.6 ", 1)[0]
    assert (
        "The missing-stop attach (§8.8 rules 3 to 5) is `sl.attached` with its reason: "
        "`record_in_force` for the recorded stop, `no_record_in_force` or `trigger_passed` for "
        "the profile fallback."
    ) in _words(section)


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
    assert (
        "Both are written ahead, the loosening before its request leaves and a refusal before its "
        "`403` or, for an automated writer, before the write is dropped"
    ) in text
    assert (
        "a rule action's, `actor_type: rule`, its fire also recorded as `rule.blocked`; a §10.7 "
        "trail's or breakeven's, `actor_type: system`"
    ) in text
    assert (
        "with the actor, role and account, the position as the object, and the stop before and "
        "after (trigger price, the size in Partial mode, and a native trail's distance and "
        "activation price). A refusal is outcome `denied`."
    ) in text
    assert "`amendOrder` and `amendTradeGroup` refuse a looser stop as their own" in text


def test_set_position_tp_sl_lets_only_the_owner_loosen_under_a_step_up() -> None:
    op = _OPS["setPositionTpSl"]
    text = _words(op["description"])
    for phrase in (
        "**Only the owner can loosen a stop** (24-internal-schemas.md section 8.8 rule 5)",
        "needs the owner's role and a live `sl_loosen` step-up, a no-grace class (one fresh code "
        "per loosening, bound to the request)",
        "the owner without one gets `403 step_up_required` (`action_class: sl_loosen`)",
        "and any other role `403 risk_limit_breached`, its refusal audited "
        "(`sl.loosen_refused`), with nothing sent",
        "The owner's loosening is audited before it is sent (`sl.loosened`)",
        "in Partial mode an `sl_size` below the lesser of the recorded cover and the position's "
        "size; or a trail that is wider or armed later or",
        "pass `null` explicitly to clear the take-profit (the stop-loss of an open position is "
        "never cleared, below)",
        "**A trail is never cleared here.** `trailing_stop: null` over a trail is refused for "
        "every role, the owner included, with `400 validation_failed` (rule "
        "`trail_clear_unsupported`) before any record or audit is written",
        "a tightening is never refused by it (C-2.6)",
    ):
        assert phrase in text, phrase
    assert "sl_loosen" in _step_up_classes()
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
