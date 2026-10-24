"""Contract (#913, E29-T04 slice 4): the exit routes' texts that sub-slices B to G code against,
read from 22 (`amendOrder`, `cancelOrder`, `cancelAllOrders`, `placeOrder`'s `ETag`, `OrderId`),
24 (8.4's exit routes, 8.7, 8.8 rule 6, 15.5, 19), 21 (3.3.11, 10.7) and 20 (12.1), never from a
copy: the orchestrator's slice-4 rulings of 2026-10-24 (issuecomment-6381292953, Q1 to Q12, Q14).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.oms_wiring import ORDER_ALERTS
from candleviewer.statechart.bindings.b01_order import NATIVE_STOP_REQUIRED
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT, CV_KILL_CANCEL_TIMEOUT

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_COMPONENTS: dict[str, Any] = _SPEC["components"]
_OPS: dict[str, Any] = {
    op["operationId"]: op
    for item in _SPEC["paths"].values()
    for op in item.values()
    if isinstance(op, dict) and "operationId" in op
}
_STATUS: dict[str, int] = {entry["code"]: entry["status"] for entry in _SPEC["x-error-codes"]}
_ARCH, _SCHEMA_DOC, _INTERNAL_DOC, _CATALOGUE = (
    (OPENAPI_SPEC_PATH.parent / name).read_text(encoding="utf-8")
    for name in (
        "20-architecture.md",
        "21-database-schema.md",
        "24-internal-schemas.md",
        "28-statechart-catalogue.md",
    )
)


def _words(text: str) -> str:
    """A description on one line: a YAML block keeps its line breaks, a phrase may span two."""
    return " ".join(text.split())


def _between(text: str, start: str, end: str) -> str:
    return _words(text.split(start, 1)[1].split(end, 1)[0])


def _missing(text: str, *statements: str) -> list[str]:
    return [statement for statement in statements if statement not in text]


def _answers(name: str) -> dict[str, str]:
    """`name`'s shared responses, by status, as the names of their components."""
    responses = _OPS[name]["responses"].items()
    return {status: ref["$ref"].rsplit("/", 1)[1] for status, ref in responses if "$ref" in ref}


_AMEND, _CANCEL, _CANCEL_ALL = (
    _words(_OPS[name]["description"]) for name in ("amendOrder", "cancelOrder", "cancelAllOrders")
)
_INFO = _words(_SPEC["info"]["description"])
_EXITS = _between(_INTERNAL_DOC, "**The exit routes (E29-T04 slice 4;", "**`TradingSwitches`")
_RULE_6 = _words(_INTERNAL_DOC.split("6. **The recorded stop (SR-E29-06", 1)[1].split("\n", 1)[0])
_RECORDS = _between(_INTERNAL_DOC, "### 15.5 ", "### 15.6 ")
_READERS = _between(_SCHEMA_DOC, "**Writers and readers.**", "**Audit, actor and time.**")
_METRIC = _between(_ARCH, "| OMS | `oms_exit_refused_total{operation,code}` |", "\n")
_TAG = '"0a000000-0000-4000-8000-000000000003:7"'


def test_an_amend_clears_nothing_and_moves_tpsl_only_on_an_unfilled_full_mode_entry() -> None:
    """Q3: a clear needs a B1 chart and a port change outside #913; a stop is never cleared
    (C-2.6); after a fill the position's stop is `setPositionTpSl`'s (E29-T07)."""
    assert not _missing(
        _AMEND,
        "and on a recorded stop's row, it is refused with `422 order_not_amendable`",
        "`take_profit: null` is refused with `validation_failed` / `tpsl_clear_unsupported`",
        "is never cleared, for good (C-2.6, arch P4): `stop_loss: null` on it is refused",
        "is taken only on an entry under `tpsl_mode: Full` with no fill",
        "`tpsl_after_fill`, `tpsl_partial_mode` or `reduce_only_tpsl` (#913 slice 4 ruling Q3)",
        "An `Offset` is resolved to a price server-side as on `placeOrder`",
        "A `qty` not above the filled quantity is `validation_failed` / `qty_not_above_filled`",
    )
    assert "clears them" not in _AMEND  # the old "`null` clears" text is gone
    assert _answers("amendOrder")["400"] == "BadRequest"
    assert (_STATUS["validation_failed"], _STATUS["order_not_amendable"]) == (400, 422)


def test_an_amend_records_its_stop_as_the_entrys_and_loosens_against_neither_stop() -> None:
    """Q2 with its rider (no fourth `source`, so no migration) and Q4: one ratchet, two
    comparisons, refused as the amend's own risk refusal."""
    assert not _missing(
        _AMEND,
        "with its position's recorded stop in force (Full mode, same side)",
        "records the stop it requests as the entry's own before the send (ruling Q2)",
    )
    assert not _missing(
        _RULE_6,
        "(`entry_attach` with the order's id, in one INSERT)",
        "audited `sl.modified` and `tp.modified` with reason `amend`",
        "with the order's current stop and with the key's record in force (Full mode, same side)",
    )
    assert "written at `VALIDATE`, or by an amend of the entry's terms (audit reason" in _READERS
    assert "CHECK (source IN ('entry_attach','trading_stop','restore'))" in _SCHEMA_DOC
    assert "(`risk_limit_breached`, the amend's own risk refusal, never `sl.loosen_refused`)" in (
        _RECORDS
    )


@pytest.mark.parametrize(
    ("tag", "taken"),
    [
        (_TAG, True),
        (_TAG.replace(":7", ":0"), True),
        (f"W/{_TAG}", False),  # weak
        ("*", False),
        (f"{_TAG}, {_TAG.replace('0a', '0b', 1)}", False),  # a list
        (_TAG.replace(":7", ":07"), False),
        (_TAG.strip('"'), False),  # not quoted
    ],
)
def test_an_order_etag_is_one_strong_tag_of_its_id_and_seq(tag: str, taken: bool) -> None:
    pattern = _COMPONENTS["headers"]["OrderETag"]["schema"]["pattern"]
    assert (re.fullmatch(pattern, tag) is not None) is taken


def test_the_etag_is_sent_on_both_202s_and_checked_after_the_404_and_the_422() -> None:
    """Q5: under the order's lock, kept by the 24 h record; `*`, a list, a weak or unparseable
    tag and another order's are 412; no `If-Match` is last write wins."""
    for name in ("placeOrder", "amendOrder"):
        assert _OPS[name]["responses"]["202"]["headers"]["ETag"]["$ref"].endswith("/OrderETag")
    header = _COMPONENTS["headers"]["OrderETag"]
    assert "required" not in header
    assert not _missing(
        _words(header["description"]),
        '`"<orderId>:<seq>"`, a strong tag of the order answered',
        "the `seq` of its latest `order_events` row",
        "which compares it under the order's lock (#913 slice 4 ruling Q5;",
    )
    placed = _words(_OPS["placeOrder"]["responses"]["202"]["description"])
    assert "on both replays, the 24 h record's stored tag and the anchor's current one" in placed
    assert (
        "a replay carries the stored one" in _OPS["amendOrder"]["responses"]["202"]["description"]
    )
    assert not _missing(
        _AMEND,
        "without `If-Match` it applies to the order as it stands (last write wins)",
        "`*`, a list of tags, a weak or unparseable tag and another order's tag are `412` too",
        "(`404`, or `403` as `OrderId` says), whether it takes an amend (`422`), then `If-Match`",
        "compared under the order's lock right before the send",
    )
    assert "an amend's with its stored `ETag`" in _EXITS
    assert "the facade compares under the order's lock (`412 version_conflict`" in _EXITS
    assert _answers("amendOrder")["412"] == "PreconditionFailed"


def test_a_view_only_grant_is_a_403_and_a_frozen_or_missing_grant_a_404() -> None:
    """Q7, and Q6's own orders (04 section 7.2.2 rows 12 to 14) with `requires_trade`."""
    assert not _missing(
        _words(_COMPONENTS["parameters"]["OrderId"]["description"]),
        "so is one on an account whose grant is frozen",
        "holds a view-only grant on is `403 account_scope_denied`",
        "a Manager's request on an order another user created is `403 forbidden`",
        "an order no person created is the Owner's alone",
    )
    assert not _missing(
        _EXITS,
        "RBAC: `orders:write` with `requires_trade`",
        "no grant on, or only a frozen one, or on a deleted account or one of another environment",
        "one on an account the caller may only view is `403 account_scope_denied`",
        "the creator being the order's trade group's `created_by`, else its anchor's",
        "with every OMS order on them in scope (row 14)",
    )
    assert (_STATUS["forbidden"], _STATUS["account_scope_denied"]) == (403, 403)


def test_a_cancel_takes_no_unresolved_order_and_no_recorded_stop_on_an_open_position() -> None:
    """Q8 (SR-E29-06 (ii) moved to E29-T06, and the residual named) and Q9 (fail closed)."""
    assert not _missing(
        _CANCEL,
        "waited for at most `CV_COMMAND_TIMEOUT`",
        "`unknown`, `quarantined`, `held` or `untracked` is refused with `409 conflict`",
        "until E29-T06 an `unknown` order is cancelled only by a KILL (#913 slice 4 ruling Q8)",
        "answered `403 risk_limit_breached`, while its position is open, or while the position",
        "once the position is flat the row can be cancelled (ruling Q9)",
    )
    assert "(SR-E29-06 (ii), moved from E29-T04 by #913 slice 4 ruling Q8" in _READERS
    assert "(SR-E29-06 (ii), E29-T04)" not in _SCHEMA_DOC + _INTERNAL_DOC
    assert "the foreign-stop cancel of SR-E29-06 (ii) is E29-T06's, ruling Q8" in _RULE_6
    assert "so an `unknown` order is cancelled only by a KILL" in _METRIC


def test_only_an_amend_that_increases_exposure_meets_the_flag_the_switches_and_the_arm() -> None:
    """Q10, amended: the flag too; every other amend and every cancel meet none (C-2.6)."""
    assert not _missing(
        _AMEND,
        "or moves a conditional entry's trigger, increases exposure: it meets every check",
        "the `trading.oms_enabled` flag, live trading enabled, the B18 kill switch, the",
        "Every other amend meets none of them",
    )
    assert "never meets the arm token" in _CANCEL and "never meets the arm token" in _CANCEL_ALL
    assert not _missing(
        _EXITS,
        "risk-increasing when it raises the quantity of an order that is not reduce-only",
        "for a risk-increasing amend on a live account only",
        "for a risk-increasing amend only, the `trading.oms_enabled` flag, then the switches",
    )
    assert "meets the arm token and the `trading_disabled` checks: the carve-out" in _INFO
    q10 = "an `amendOrder` that increases exposure (#913 slice 4 ruling Q10)"
    assert q10 in _words(_COMPONENTS["responses"]["Forbidden"]["description"])
    assert q10 in _between(_SCHEMA_DOC, "### 10.7 Feature flags", "### 10.8 ")


def test_the_exit_routes_check_answer_and_audit_as_ruled() -> None:
    """24's steps in order; Q11's answers, its in-flight guard and no anchor (OM-T11); one
    shared 409; Q12's records."""
    section = _INTERNAL_DOC.split("**The exit routes (E29-T04 slice 4;", 1)[1]
    heads = re.findall(r"^\d+\. ([^:,(;]+)", section.split("\n\nEach ", 1)[0], re.MULTILINE)
    assert [head.strip() for head in heads] == [
        *("the principal", "RBAC", "the OMS runtime", "the scope", "the body", "the arm token"),
        *("`Idempotency-Key`", "the 24 h record", "the in-flight guard"),
        *("for a risk-increasing amend only", "the exit service"),
    ]
    conflict = _COMPONENTS["responses"]["OrderExitConflict"]
    assert conflict["headers"]["Retry-After"] == {"$ref": "#/components/headers/RetryAfter"}
    codes = set(re.findall(r"`([a-z_]+)`", conflict["description"]))
    assert {code: _STATUS[code] for code in codes} == dict.fromkeys(
        ("idempotency_key_reuse", "idempotency_in_flight", "stop_request_in_flight", "conflict"),
        409,
    )
    shared = {"400": "BadRequest", "409": "OrderExitConflict", "501": "NotImplemented"}
    for name in ("amendOrder", "cancelOrder", "cancelAllOrders"):
        assert _answers(name).items() >= shared.items(), name
    for name, text in (("amendOrder", _AMEND), ("cancelOrder", _CANCEL)):
        assert _answers(name)["429"] == "RateLimited"
        assert not _missing(
            text,
            "`502 exchange_error` with `exchange.ret_code` when it refused it",
            "`429 exchange_rate_limited` with `Retry-After` when no rate token was free",
            "`202` with the order `unknown` when the outcome is not known, never re-sent",
        )
    assert "keep no anchor (threat model OM-T11): their 24 h record holds only a `2xx`" in _INFO
    assert "is `409 idempotency_in_flight` with `Retry-After: 1`, from a bounded" in _INFO
    assert not _missing(
        _EXITS,
        "a repeat while the first runs is `409 idempotency_in_flight` with `Retry-After: 1`",
        "`409 conflict` for a machine latched degraded (CV-C63)",
        "`202` with the order `unknown` when the command port raised",
        "a real order's `404` included and another user's order with reason `not_order_creator`",
        "while a missing id writes no record (ruling Q12)",
        "every other as `orders.amend` or `orders.cancel` with outcome `denied` and its code",
        "Each order a cancel-all cancels is `orders.cancel` with reason `cancel_all`",
    )
    assert not _missing(
        _RECORDS,
        "request cancels is `orders.cancel` with reason `cancel_all`",
        "is `rbac.denied` with reason `not_order_creator`, as is the `404` for an order that",
    )
    assert {"orders.amend", "orders.cancel", "rbac.denied"} <= AUDIT_ACTIONS


def test_cancel_all_cancels_order_by_order_and_folds_only_what_a_read_proves() -> None:
    """Q1 with its fail-safe rider, the selection, row 14's scope, the bound and the deadline."""
    assert not _missing(
        _CANCEL_ALL,
        "each by its own order command, written ahead and audited",
        "Only an unrestricted request (`intents` empty, `exclude_reduce_only: false`) is folded",
        "only where an open-orders read shows each plain order resting there selected",
        "any other is cancelled order by order",
        "and the server keeps to it (24-internal-schemas.md section 8.7)",
        "(`provenance` `placed`; never a recorded stop's row)",
        "a reduce-only order only with `exclude_reduce_only: false`",
        "(04-security-program.md section 7.2.2 row 14)",
        "At most five accounts are worked at once, one order at a time on each, within a 20 s",
    )
    failures = _CANCEL_ALL.split("else `error` gives its first failure:", 1)[1]
    for code in ("exchange_error", "exchange_rate_limited", "exchange_unavailable", "timeout"):
        assert f"`{code}`" in failures and code in _STATUS, code
    assert "exchange_ret_code" in _COMPONENTS["schemas"]["LegError"]["properties"]
    assert not _missing(
        _between(_INTERNAL_DOC, "### 8.7 Rate budgeting", "### 8.8 "),
        "`order.cancel_all` 1/s (linear)",
        "Only an unrestricted request (no `intents`, `exclude_reduce_only: false`) joins",
        "otherwise that account and symbol fall back to per-order cancels, the fail-safe",
        "At most one venue `cancel-all` per UID per second leaves",
        "until E34-T02's governor takes it over (#859)",
    )
    fields = _COMPONENTS["schemas"]["CancelAllRequest"]["properties"]
    assert fields["exclude_reduce_only"]["default"] is True
    assert "recorded stop's row is never cancelled" in fields["exclude_reduce_only"]["description"]
    assert "granted accounts that allow trading" in fields["exchange_account_ids"]["description"]


def test_the_exit_refusals_are_counted_and_the_change_is_logged() -> None:
    """Q14: the counter, its labels, its catalogue entry with the code that counts it (as H0's
    was); 24 section 19's entry, numbered after main's last one."""
    assert not _missing(
        _METRIC,
        "by `operation` (`amend`, `cancel`, `cancel_all`) and problem code",
        "Its catalogue entry lands with the code that counts it (E29-T04 slice 4)",
    )
    assert "`oms_exit_refused_total{operation,code}`" in _EXITS
    numbers = [int(n) for n in re.findall(r"^### 19\.(\d+) ", _INTERNAL_DOC, re.MULTILINE)]
    assert numbers == list(range(1, len(numbers) + 1))  # one entry per number, in order
    title = r"^### 19\.(\d+) 2026-10-24 — .*: the exit routes' contract \(E29-T04, #913\)$"
    found = re.search(title, _INTERNAL_DOC, re.MULTILINE)
    assert found is not None
    entry = _between(_INTERNAL_DOC, found.group(0), "\n### ")
    assert f"This number follows `main`'s last entry, §19.{int(found.group(1)) - 1};" in entry
    assert 'the new header `OrderETag`, a strong `"<orderId>:<seq>"`' in entry


def test_the_s4b1_ruling_bounds_a_cancel_and_ends_its_110001_in_reconciliation() -> None:
    """The orchestrator's S4-B1 ruling of 2026-10-24 09:23Z, carried in S4-A: the two cancel
    bounds, the recorded stop's refusal and no KILL of it, a `110001` ended from `unknown`, a
    KILL's three records, and an `ETag` that only a lifecycle step moves."""
    rate = _between(_INTERNAL_DOC, "### 8.7 Rate budgeting", "### 8.8 ")
    assert not _missing(
        rate,
        "`critical` up to the 5 s below",
        "a user's cancel at `CANCEL_TIMEOUT_S`, 9 s, past the `critical` lane's 5 s token wait",
        "a KILL's cancel at `KILL_CANCEL_TIMEOUT_S`, 4 s, inside B1's 5 s kill cancel",
    )
    assert 4 < CV_KILL_CANCEL_TIMEOUT == 5 < 9 < CV_COMMAND_TIMEOUT
    assert "within the `critical` lane's 5 s wait, inside the cancel's 9 s bound" in _CANCEL
    assert NATIVE_STOP_REQUIRED == "NATIVE_STOP_REQUIRED"
    assert not _missing(
        _EXITS,
        "the command port refuses it with `NATIVE_STOP_REQUIRED` while its position is open",
        "a KILL never cancels such a row, reading and sending nothing for it",
        "or when a cancel met `110001` or a fill raced it (§8.6), never re-sent",
        "so only a lifecycle step moves it",
    )
    assert not _missing(
        _CANCEL,
        "refused by the command port (`NATIVE_STOP_REQUIRED`)",
        "A KILL never cancels such a row",
        "already terminal (`110001`) is no refusal",
        "the cancel answers `202` with the order `unknown`, never re-sent, until reconciliation",
    )
    errors = _between(_INTERNAL_DOC, "### 8.6 Error mapping", "### 8.7 ")
    assert "On cancel: treat as already-terminal, reconcile" in errors  # the 110001 row
    assert not _missing(
        errors,
        "On a cancel `110001` is no refusal",
        "The command port raises a typed `already_terminal` answer that carries the venue's",
        "B1 lands the order in `unknown` (S1: never re-sent), whose entry arms the reconciliation",
        "(`RECON_FOUND_CANCELLED` or `RECON_FOUND_FILLED`)",
        "`record_transport_fault` names the fault `already_terminal`",  # the 09:37Z ruling
        'reads "already terminal — reconciling", not a transport fault',
        "the alert still fires for it, as expected",
        "audited `kill_cancel_already_terminal` (§15.5) and requests the reconciliation directly",
    )
    assert not _missing(
        _RECORDS,
        "`kill_cancel_refused` for a venue refusal, with its `retCode`",
        "`rate_budget_exceeded` when no rate token was free",
        "`kill_cancel_already_terminal` for a `110001`",
    )
    assert not _missing(
        _words(_COMPONENTS["headers"]["OrderETag"]["description"]),
        "it changes with each lifecycle step the order takes and with nothing else",
        "a step of the order's `protection` region and B1's internal arms write no such row",
        "A final order's answer carries none",
    )
    assert "and with nothing else (a `protection` step leaves it)" in _AMEND


def test_the_later_s4b1_rulings_park_a_110001_and_name_what_a_kill_audits() -> None:
    """The S4-B1 rulings of 09:47Z and 09:57Z: INV-B1-h's audited outcomes (28's prose, outside
    its generated index), the Q8 residual of a parked order, a KILL of an unbound order, a large
    KILL's tail, and the `ETag` as the facade's `version()`."""
    [inv_h] = [line for line in _CATALOGUE.splitlines() if line.startswith("| **INV-B1-h** |")]
    assert (
        "the venue's refusal (`kill_cancel_refused`, with the venue's `retCode`) or a refused "
        "rate token (`rate_budget_exceeded`), is audited and never rolls the kill back" in inv_h
    )
    assert _CATALOGUE.index("| **INV-B1-h** |") < _CATALOGUE.index("<!-- BEGIN GENERATED:")
    errors = _between(_INTERNAL_DOC, "### 8.6 Error mapping", "### 8.7 ")
    assert not _missing(
        errors,
        "or a fill racing a cancel, therefore parks the order in `unknown`",
        "that branch also posts `request_reconciliation` with the order's id",
        "until E29-T06 wires the reconciler it is the operator's cue",
        "the position view is the private `position` stream's, so risk reads nothing stale",
        'a KILL of an order with no bound exchange id that meets it is audited "the venue does '
        'not hold it; reconciling", never as ended',
    )
    assert '"the venue does not hold it; reconciling", never as ended' in _RECORDS
    assert not _missing(
        _between(_INTERNAL_DOC, "### 8.7 Rate budgeting", "### 8.8 "),
        "Past about 16 cancels per UID, a large KILL's tail exceeds that 4 s per-order bound",
        "times out unsent, audited `kill_cancel_timeout`",
        "as B18's cancel-all and E34-T02's reserve land before live",
    )
    assert not _missing(
        _METRIC,
        "or a fill racing a cancel, parks its order in `unknown` (never re-sent)",
        'its `order_already_terminal` ticket ("already terminal — reconciling", §12.5) is the',
        "is the operator's cue until E29-T06 wires the reconciler",
    )
    assert not _missing(
        _words(_COMPONENTS["headers"]["OrderETag"]["description"]),
        "the last committed one, which is the order facade's `version()`",
        "neither does an answer given during a resync window",
    )
    assert not _missing(
        _EXITS,
        "the facade's `version()`, the `event_seq` of its last committed lifecycle row",
        "during a resync window (as `state()` gives none) or for a final order",
    )


def test_an_already_terminal_cancel_is_a_ticket_and_a_transport_fault_still_pages() -> None:
    """The orchestrator's 10:01Z ruling: `order_already_terminal` is a ticket with its payload,
    a real transport fault keeps paging as `order_unknown`, and 20 section 12.5 routes every
    order alert the router knows (`ORDER_ALERTS`) as the code does."""
    assert not _missing(
        _between(_INTERNAL_DOC, "### 8.6 Error mapping", "### 8.7 "),
        "Its alert is `order_already_terminal`, a ticket, not a page",
        "with the order's id and the venue's `retCode`",
        "a real transport fault keeps paging as `order_unknown`",
    )
    routes = _between(_ARCH, "OMS order alerts (E29-T03, E29-T04;", "\n")
    page, ticket = routes.split("Page — ", 1)[1].split("; Ticket — ", 1)
    assert set(re.findall(r"`([A-Za-z_]+)`", page)) == ORDER_ALERTS - {
        "order_never_sent",
        "order_already_terminal",
    }
    assert re.findall(r"^`([a-z_]+)`.* and `([a-z_]+)`", ticket) == [
        ("order_never_sent", "order_already_terminal")
    ]
    assert (
        "payload \"already terminal — reconciling\" with the order's id and the venue's" in ticket
    )
    assert "the order still parks in `unknown`, never re-sent, S1" in ticket


def test_a_read_that_fails_before_the_send_is_a_503_and_leaves_the_order_live() -> None:
    """The S4-B1 rulings of 10:18Z and 10:29Z: an amend's or a cancel's failed read before
    anything is sent is `503 store_unavailable`, the order live and cancellable, audited denied;
    a KILL's is `kill_cancel_refused` and counted, and it sends nothing it could not read."""
    for text in (_AMEND, _CANCEL):
        assert not _missing(
            text,
            "that fails answers `503 store_unavailable` with `Retry-After`",
            "nothing was sent, so the order stays live and cancellable, never `unknown`",
        )
    assert _answers("amendOrder")["503"] == _answers("cancelOrder")["503"] == "ServiceUnavailable"
    assert _STATUS["store_unavailable"] == 503
    assert not _missing(
        _EXITS,
        "that fails answers `503 store_unavailable` with `Retry-After`: nothing was sent",
        "An amend's command port audits it `orders.amend` denied, reason `store_unavailable`, "
        "and raises when that record cannot be written (C-2.9)",
        "a user's cancel is audited `orders.cancel` denied, reason `store_unavailable`, by the "
        "exit service, the port writing none",
        "Raising, which puts the order in `unknown`, stays only once the venue call has started",
        "audited `kill_cancel_refused` with the code `store_unavailable`, and the KILL stays final",
        "as it cannot tell a recorded stop from a plain order (fail closed)",
        '("n cancels not sent — store unavailable") rather than reporting a clean KILL',
    )
    assert not _missing(
        _RECORDS,
        "is `orders.amend` or `orders.cancel` denied with reason `store_unavailable`",
        "the KILL's `halted_by_kill` record counts the cancels it did not send, by code",
    )
