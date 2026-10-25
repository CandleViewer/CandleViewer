"""Contract (#913, E29-T04 slice 4): the exit routes' texts that sub-slices B to G code against,
read from 22 (`amendOrder`, `cancelOrder`, `cancelAllOrders`, `placeOrder`'s `ETag`, `OrderId`),
24 (8.4's exit routes, 8.7, 8.8 rule 6, 15.5, 19), 21 (3.3.11, 10.7) and 20 (12.1), never from a
copy: the orchestrator's slice-4 rulings of 2026-10-24 (issuecomment-6381292953, Q1 to Q12, Q14),
and S4-D2a's (SEC-S4C2B-01; the rulings of 20:58Z and 21:47Z, and of 2026-10-25 00:27Z, 00:36Z,
01:11Z, 01:24Z and 02:50Z (2); the code lens's CR-S4D2A-02, -04 and -07).
"""

from __future__ import annotations

import json
import re
from typing import Any, get_args

import pytest

from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.api.order_problems import order_problem
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.observability.correlation import CORRELATION_HEADER
from candleviewer.oms.errors import OmsError
from candleviewer.oms.exits import ALREADY_FINAL, RECLASSIFIED, ExitStep
from candleviewer.oms.recovery import FINALS
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
    tag and another order's are 412; no `If-Match` is the order as it stands when the amend is
    admitted (Q5 as amended, SEC-S4C2B-01)."""
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
        "without `If-Match` it applies to the order as it stands when the amend is admitted",
        "`*`, a list of tags, a weak or unparseable tag and another order's tag are `412` too",
        "the order's scope (`404`, or `403` as `OrderId` says) first, whether it takes an "
        "amend (`422`) after the body's shape, the gates and the 24 h record, and `If-Match` "
        "(`412`) last",
        "compared under the order's lock right before the send",
    )
    assert "an amend's with its stored `ETag`" in _EXITS
    assert "the facade compares under the order's lock (`412 version_conflict`" in _EXITS
    assert _answers("amendOrder")["412"] == "PreconditionFailed"


def test_a_view_only_grant_is_a_403_and_a_frozen_or_missing_grant_a_404() -> None:
    """Q7, and Q6's own orders (04 section 7.2.2 rows 12 to 14), the trade grant judged with the
    order at step 4, as step 2 knows no account yet (vw3's code look on S4-D1b, item 10)."""
    assert not _missing(
        _words(_COMPONENTS["parameters"]["OrderId"]["description"]),
        "so is one on an account whose grant is frozen",
        "holds a view-only grant on is `403 account_scope_denied`",
        "a Manager's request on an order another user created is `403 forbidden`",
        "an order no person created is the Owner's alone",
    )
    assert not _missing(
        _EXITS,
        "RBAC: `orders:write` alone, `403 forbidden` without the permission, as no account is "
        "known yet: the trade grant is step 4's",
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
        "reduce-only (a resting entry repriced to a marketable price fills at once), increases "
        "exposure (24-internal-schemas.md section 8.10 defines it): it meets every check",
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
        (
            *("idempotency_key_reuse", "idempotency_in_flight", "stop_request_in_flight"),
            *("account_unavailable", "conflict"),
        ),
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
    failures = _CANCEL_ALL.split("else `error` gives its first failure", 1)[1]
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
        "On a cancel, B1's own or a KILL's",
        "`110001` is no refusal",
        "The command port raises the adapter's `NotFoundError` (code `ORDER_NOT_FOUND`, an",
        "`ExchangeError`, never a `LookupError` or `ValueError`) carrying the venue's `retCode`",
        "B1 lands the order in `unknown` with the reason `already_terminal` (S1: never re-sent)",
        "(`RECON_FOUND_CANCELLED` or `RECON_FOUND_FILLED`)",
        "`record_transport_fault` names the fault `already_terminal`",  # the 09:37Z ruling
        'reads "already terminal — reconciling", not a transport fault',
        "the alert still fires for it, as expected",
        "audited `kill_cancel_already_terminal` (§15.5) and requests the reconciliation directly",
    )
    assert not _missing(
        _RECORDS,
        "each a registered `B1_AUDITS` row (SR-E29-17;",
        "`kill_cancel_refused` (error) for a venue refusal, with its `retCode`",
        "`kill_cancel_rate_budget_exceeded` (error) when no rate token was free",
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
        "rate token (`kill_cancel_rate_budget_exceeded`), is audited and never rolls the kill "
        "back" in inv_h
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
    assert (
        "an order a cancel's `110001`, or a fill racing a cancel, parks in `unknown` (never "
        "re-sent; 24 §8.6) waits for E29-T06's reconciler, its ticket (§12.5) the operator's cue"
        in _METRIC
    )
    assert "already terminal — reconciling" not in _METRIC  # 24 §8.6 owns the payload
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
            "that fails answers `503 store_unavailable` with `Retry-After: 1`",
            "nothing was sent, so the order stays live and cancellable, never `unknown`",
        )
    assert _answers("amendOrder")["503"] == _answers("cancelOrder")["503"] == "ServiceUnavailable"
    assert _STATUS["store_unavailable"] == 503
    assert not _missing(
        _EXITS,
        "with `Retry-After: 1`, one shared value for the cancel and the amend: nothing was sent",
        "An amend's command port audits it `orders.amend` denied, reason `store_unavailable`, "
        "and raises when that record cannot be written (C-2.9)",
        "a user's cancel is audited `orders.cancel` denied, reason `store_unavailable`, by the "
        "exit service, the port writing none",
        "Raising, which puts the order in `unknown`, stays only once the venue call has started",
        "audited `kill_cancel_refused` with the code `STORE_UNAVAILABLE`, or "
        "`ACCOUNT_UNAVAILABLE` for an account it cannot send for, and the KILL stays final",
        "as it cannot tell a recorded stop from a plain order (fail closed)",
        "Each KILL logs one `oms_kill_result` with its cancels counted by outcome, those still in "
        "flight included (a re-sent KILL reports its own), and any cancel not done pages, naming "
        "the count by code",
        "so the operator never reads a clean KILL; `kill()`'s signature and answer are unchanged",
    )
    assert not _missing(
        _RECORDS,
        "is `orders.amend` or `orders.cancel` denied with reason `store_unavailable`",
        "the KILL's one `oms_kill_result` log counts its cancels by outcome, any not done paged by",
    )


def test_an_account_it_cannot_send_for_and_cancel_alls_counting_are_as_ruled() -> None:
    """The orchestrator's rulings of 2026-10-24 11:31Z to 11:45Z, with S4-B1's final names: an
    account the command port cannot send for is `409 account_unavailable` with no retry, one 1 s
    retry for `store_unavailable`, a `110001`'s reconciliation request a ticket, the recorded
    stop's read cap, cancel-all's counting, and SR-E29-06 (ii) in E29-T06's hands."""
    [entry] = [e for e in _SPEC["x-error-codes"] if e["code"] == "account_unavailable"]
    assert (entry["status"], entry["retryable"]) == (409, False)
    for text in (_AMEND, _CANCEL):
        assert not _missing(
            text,
            "answers `409 account_unavailable`, with no `Retry-After`",
            "nothing was sent, the order stays live, and the operator is paged",
        )
    conflict = _words(_COMPONENTS["responses"]["OrderExitConflict"]["description"])
    assert (
        "`account_unavailable`, without `Retry-After`, for an order whose account the OMS cannot "
        "send for" in conflict
    )
    assert not _missing(
        _EXITS,
        "the port answers `ACCOUNT_UNAVAILABLE` with no `retry_after_s`, B1 keeps the order live, "
        "the route answers `409 account_unavailable` with no `Retry-After`",
        "and the wiring's CRITICAL page stays",
    )
    assert "one whose account cannot be sent for with reason `account_unavailable`" in _RECORDS
    rate = _between(_INTERNAL_DOC, "### 8.7 Rate budgeting", "### 8.8 ")
    assert (
        "is capped at `RECORDED_STOP_READ_S`, 3 s, so the `critical` lane keeps its 5 s token "
        "wait inside the 9 s" in rate
    )
    errors = _between(_INTERNAL_DOC, "### 8.6 Error mapping", "### 8.7 ")
    assert (
        "One case gives the operator exactly one notice: for a user's cancel the "
        "`order_already_terminal` ticket, which carries the request" in errors
    )
    assert not _missing(
        _between(_ARCH, "OMS order alerts (E29-T03, E29-T04;", "\n"),
        "one case raises exactly one ticket, the alert carrying the request for a user's cancel "
        "and the request alone for a KILL's bound `110001`",
        "Until E29-T06 / T08 the `oms_unknown_orders` page also counts an order parked by",
    )
    assert (
        "until E29-T06 / T08 the unknown-orders alert (`oms_unknown_orders`, §12.5) also counts "
        "orders parked by `110001`, and the ticket names the reason" in _METRIC
    )
    failures = _CANCEL_ALL.split("else `error` gives its first failure", 1)[1]
    for code in ("store_unavailable", "account_unavailable", "conflict"):
        assert f"`{code}`" in failures and code in _STATUS, code
    assert not _missing(
        _CANCEL_ALL,
        "an order that filled before its cancel landed is neither affected nor an error",
        "a cancel already sent stays with its order and is never sent again",
        "counts in neither `affected` nor `error`",
        "`requested` counts the accounts the request covers once its scope check passed, and "
        "`succeeded` those `ok`",
        "as an order's conflicts are reported in `results`, never as a `409`",
        "`503 store_unavailable` when the scope itself cannot be read, nothing sent",
    )
    threat = OPENAPI_SPEC_PATH.parents[1] / "security" / "threat-models" / "E29-oms.md"
    assert "the OMS cancel service, which E29-T06 builds and E29-T07's route calls" in _words(
        threat.read_text(encoding="utf-8")
    )


def test_the_contract_lens_fold_defines_once_and_closes_the_gaps() -> None:
    """S4-A's contract-lens fold (2026-10-24): one definition of a risk-increasing amend in
    24 section 8.10, the amend's risk check, the version an amend carries (SEC-S4C2B-01 since),
    the guard's bound, the one pre-send path to `unknown`, cancel-all's open points, and the
    nits."""
    [definition] = [
        line
        for line in _INTERNAL_DOC.splitlines()
        if line.startswith("**Risk-increasing amends: the one definition")
    ]
    assert not _missing(
        _words(definition),
        '"Quantity up" is the quantity raised on an order that is not reduce-only, and "trigger '
        "re-armed\" a conditional entry's trigger moved",
        "`22-api-openapi.yaml` (`amendOrder`, `ArmToken`) and §8.4's exit routes point here",
    )
    assert "(24-internal-schemas.md section 8.10 defines it)" in _AMEND
    arm = _words(_COMPONENTS["parameters"]["ArmToken"]["description"])
    assert 'which defines "quantity up" and "trigger re-armed" once' in arm
    assert not _missing(
        _AMEND,
        "and the risk check of the amended, sized and rounded order evaluated at the amended "
        "price (`403 risk_limit_breached`, SR-E29-04)",
        "class is read from the order as it stands when the amend is admitted, its version read "
        "first, and the send carries that version",
        "an amend with no `If-Match` carries the version the amend was judged at (ruling Q5, as "
        "amended on 2026-10-24: SEC-S4C2B-01)",
        "the stop-request gate, 21-database-schema.md section 3.3.11",
        "the one way an amend that sent nothing reaches `unknown`",
        "An empty body is `validation_failed` / `nothing_to_amend`",
        "`native_stop_required` for the stop and `take_profit_side` for the take-profit",
    )
    assert "after a fill `amendOrder` refuses a stop change first, `tpsl_after_fill`" in _AMEND
    assert not _missing(
        _EXITS,
        "the risk check of the amended, sized and rounded order evaluated at the amended price, "
        "the pipeline's own rule 3",
        "with `If-Match`, carrying the tag's version",
        "without it, carrying the version the exit service read before it re-read the row and "
        "judged the amend",
        "holding at most 1,024 keys",
        "a request arriving while the set, or its principal's share of it, is full is "
        "`429 rate_limited` with `Retry-After: 1`",
        "the one way an exit that sent nothing reaches `unknown`",
    )
    assert "at most 1,024 keys and 64 per caller, a request arriving while either is full" in (
        _INFO
    )
    assert "`CV_COMMAND_TIMEOUT`, 10 s (28-statechart-catalogue.md section B1.4)" in _CANCEL
    assert "such a cancel answers within about 21 s" in _CANCEL
    assert not _missing(
        _CANCEL_ALL,
        "a plain order is one the venue's cancel-all with `orderFilter=Order` cancels",
        "the account's other selected orders still each sent theirs",
        "and neither is one a `110001` parks in `unknown`",
        "takes a new `Idempotency-Key`: the same key replays the stored `200` for 24 h",
        "once the body is read (the scope needs its ids)",
        "an empty list from a caller with no trade grant answers `200` with no results",
        "and the refusal is audited, one `rbac.denied` record for the request",
    )
    ids = _COMPONENTS["schemas"]["CancelAllRequest"]["properties"]["exchange_account_ids"]
    assert (ids["maxItems"], ids["uniqueItems"]) == (100, True)
    errors = _between(_INTERNAL_DOC, "### 8.6 Error mapping", "### 8.7 ")
    assert "On a cancel, B1's own or a KILL's (an algo's `cancel_children`, §9.5" in errors
    assert "the parked order also counts in `oms_unknown_orders`, whose rule pages" in errors
    assert "An amend's own `entry_attach` rows (24 §8.8 rule 6, audit reason `amend`) are " in (
        _words(_SCHEMA_DOC)
    )
    assert "`order.adopted_untracked`, `orders.amend`, `orders.cancel`," in _RECORDS
    assert "until then the `202` carries none" in _words(
        _OPS["placeOrder"]["responses"]["202"]["description"]
    )
    assert "A client treats it as opaque" in _words(
        _COMPONENTS["headers"]["OrderETag"]["description"]
    )
    assert "a narrowing of a request no route served yet" in _INTERNAL_DOC
    conflict = _words(_COMPONENTS["responses"]["OrderExitConflict"]["description"])
    assert "On `cancelAllOrders` only the two idempotency codes apply" in conflict


def test_the_1230z_rulings_word_the_deadline_the_retryable_flags_and_an_unbound_kill() -> None:
    """The orchestrator's 12:30Z rulings: vw3's readings 3 and 4 for cancel-all, and S4-B1's
    final names: an unbound KILL's `110001` (`not_held_unbound`, paged, not done), the account
    refusal's two sources and the KILL result's in-flight count."""
    assert not _missing(
        _CANCEL_ALL,
        "reports `timeout`, which replaces any failure it met before, so the retryable signal wins",
        "`retryable` is true for `store_unavailable`, `timeout` and `exchange_rate_limited`, and "
        "false for `exchange_unavailable`, `conflict`, `account_unavailable` and `exchange_error`",
    )
    errors = _between(_INTERNAL_DOC, "### 8.6 Error mapping", "### 8.7 ")
    assert not _missing(
        errors,
        "its `request_reconciliation` carries the reason `not_held_unbound` and pages, and the "
        "cancel counts as not done in the KILL's result",
        "Only a cancel's `NotFoundError` reads as already terminal",
    )
    assert "a paged `request_reconciliation` with the reason `not_held_unbound`" in _RECORDS
    assert not _missing(
        _EXITS,
        "(its `AccountScopeDenied`, or `OrderEntryRefused` with `no_active_key`)",
        "those still in flight included (a re-sent KILL reports its own)",
    )
    routes = _between(_ARCH, "OMS order alerts (E29-T03, E29-T04;", "\n")
    assert "as does an unbound KILL cancel's, reason `not_held_unbound`" in routes
    assert (
        "the request itself going only to the internal seam E29-T06's job consumes, never "
        "ticketed on its own; for a KILL's bound `110001` the request alone, as a ticket" in errors
    )


def test_the_0656z_ruling_makes_a_not_ready_cancel_retryable() -> None:
    """The orchestrator's ruling of 2026-10-25 06:56Z (2): `oms_not_ready`, the gateway's
    backpressure (S4-D2a's SEC-S4D2A-01) or the exit service closing, is transient, so cancel-all
    reports it `retryable`."""
    assert not _missing(
        _CANCEL_ALL,
        "true for `oms_not_ready`, which passes (the gateway's backpressure, or the exit service "
        "closing at shutdown; the orchestrator's ruling of 2026-10-25 06:56Z)",
    )


def test_the_1742z_ruling_passes_another_per_order_refusal_through_cancel_all() -> None:
    """The orchestrator's 17:42Z ruling (S4-E): a refusal of the per-order cancel that the list does
    not name keeps its code and is not retryable; an order that ended otherwise first is, like a
    fill, neither affected nor an error; and S4-C's counting: a cancel whose step had not settled
    within its own wait is `timeout`, retryable, as the deadline is."""
    assert not _missing(
        _CANCEL_ALL,
        "or another refusal of the per-order cancel, with its code as `cancelOrder` answers it",
        "nor is one that ended otherwise first (`rejected`, `expired` or `killed`)",
        "and false for another refusal of the per-order cancel (the 17:42Z ruling)",
        "when the deadline cut it short or an order's cancel had not settled within its own wait",
    )
    assert FINALS - {"filled", "cancelled"} == {"rejected", "expired", "killed"}


def test_the_security_look_fold_gates_a_price_move_and_closes_the_lows() -> None:
    """S4-A's Fable security look at `a579bb24`: SEC-S4A-01 (a `price` or `trigger_price`
    change on an order that is not reduce-only is risk-increasing), SEC-S4A-02 (one answer for a
    port refusal whose record cannot be written), -03 (the guard's per-principal share), -04 (the
    `404` timing residual) and -05 (a parked order counts as ended; a re-sent stop ratcheted)."""
    [definition] = [
        line
        for line in _INTERNAL_DOC.splitlines()
        if line.startswith("**Risk-increasing amends: the one definition")
    ]
    assert (
        "a change of the `price` or `trigger_price` of an order that is not reduce-only is "
        "risk-increasing too" in definition
    )
    assert "a reduce-only order's price" in definition
    assert "so its risk check is evaluated at the amended price" in definition
    assert (
        "moves a conditional entry's trigger, or changes the `price` or `trigger_price` of an "
        "order that is not reduce-only" in _AMEND
    )
    assert (
        "or changes the price or trigger price of an order that is not reduce-only; every "
        "other amend" in _EXITS
    )
    assert not _missing(
        _EXITS,
        "a refusal inside the command port whose own record cannot be written is the port's "
        "raise, answered `202` with the order `unknown` (step 11)",
        "holding at most 1,024 keys and 64 per principal",
        "so a full share refuses only the principal that filled it",
        "is an accepted residual (threat model SR-E29-13)",
    )
    threat = OPENAPI_SPEC_PATH.parents[1] / "security" / "threat-models" / "E29-oms.md"
    assert "so their timing may differ: an accepted residual, bounded by authentication" in (
        _words(threat.read_text(encoding="utf-8"))
    )
    assert "an order a `110001` parks in `unknown` counting as ended" in _CANCEL_ALL
    assert "a stop re-sent unchanged is ratcheted as a changed one is" in _AMEND
    assert "has compared each stop it sends, changed or re-sent, with the order's current" in (
        _RULE_6
    )
    arm = _words(_COMPONENTS["parameters"]["ArmToken"]["description"])
    assert "once, a price move on an order that is not reduce-only with them" in arm


def test_the_delta_check_fold_points_info_to_the_one_class_and_orders_cancel_all() -> None:
    """S4-A's Opus delta check at `0d29a2bd`: DC-S4A-01 (`info`'s order of the checks names
    24 Sec.8.10's class, a price move included, and no longer its own narrower list), -02
    (cancel-all reads its body before its scope in 24 as in 22, D8) and the cancel's one way to
    `unknown` with nothing sent, as the amend's."""
    assert (
        "only an amend that increases exposure (the one class 24-internal-schemas.md section 8.10 "
        "defines, a `price` or `trigger_price` change on an order that is not reduce-only "
        "included) meets the arm token and the `trading_disabled` checks" in _INFO
    )
    assert "or moves a conditional entry's trigger) meets the arm token" not in _INFO
    assert (
        "`cancelAllOrders`, whose scope needs the ids its body lists, reads that body first, "
        "strictly (step 5's `400 validation_failed`, whatever ids a malformed body names), then "
        "refuses the whole request with `403 account_scope_denied`" in _EXITS
    )
    assert "Scope is settled before anything is sent (SR-E29-13), once the body is read" in (
        _CANCEL_ALL
    )
    assert (
        "never `unknown`, which only a venue call already started can leave, or a refusal whose "
        "own audit record cannot be written (C-2.9), the one way a cancel that sent nothing "
        "reaches `unknown`" in _CANCEL
    )
    threat = OPENAPI_SPEC_PATH.parents[1] / "security" / "threat-models" / "E29-oms.md"
    assert "bound to the caller and scope; the exit routes' `404`" in threat.read_text(
        encoding="utf-8"
    )


def test_sec_s4c2b_01_judges_an_amend_on_the_order_as_it_stands_and_sends_its_version() -> None:
    """SEC-S4C2B-01 (the orchestrator's rulings of 2026-10-24 20:58Z and 21:47Z (4)): an amend's
    class and checks are judged on the order as it stands when it is admitted, its version read
    first, and the send carries `If-Match`'s version, else the one read; a step the order took
    meanwhile is `409 conflict` with `Retry-After: 1`, never `412`, which stays the client's own
    tag; steps 6 and 10 judge the class on step 4's read, so an amend the re-read makes
    risk-increasing when that read did not is refused before the send."""
    assert not _missing(
        _AMEND,
        "an order that took a step meanwhile is refused, nothing sent, with `409 conflict` and "
        "`Retry-After: 1` for the client to send the amend again, or with `412` when the amend's "
        "`If-Match` names a version the step left behind",
        "and so is an amend that this read makes risk-increasing when the route's first read of "
        "the order, on which it judged the arm token, did not (SEC-S4C2B-01)",
        "`412` stays the answer to the client's own tag: an amend sent without `If-Match` is "
        "never refused with it",
    )
    for gone in ("B1 takes one at a time", "carries no version", "(last write wins)"):
        assert gone not in _AMEND, gone
    assert not _missing(
        _EXITS,
        "The class is read from the order as it stands when step 11 admits the amend, its version "
        "read first, so a step the order took meanwhile refuses the send; steps 6 and 10 judge it "
        "on step 4's read, and step 11 refuses an amend its own read makes risk-increasing when "
        "step 4's did not (SEC-S4C2B-01);",
        "An amend is judged on the order as it stands when the exit service admits it: its "
        "machine's state and version read together, before any wait, then its row read again, "
        "never older than that version",
        "which must be the version read and which the facade compares under the order's lock "
        "(`412 version_conflict`, ruling Q5)",
        "a step the order took meanwhile answers `409 conflict` with `Retry-After: 1`, nothing "
        "sent, never `412`",
        "is refused before the send alike: `412` with `If-Match`, `409 conflict` with "
        "`Retry-After: 1` without",
    )
    for gone in ("B1 takes one amend at a time", "carrying none (last write wins)"):
        assert gone not in _EXITS, gone
    conflict = _words(_COMPONENTS["responses"]["OrderExitConflict"]["description"])
    assert (
        "with `Retry-After: 1`, for an amend sent without `If-Match` whose order took a step while "
        "it was admitted, which the client sends again: never `412`, which answers the client's "
        "own stale tag alone" in conflict
    )


def test_a_step_11_class_refusal_is_audited_naming_its_step_and_its_reason() -> None:
    """The orchestrator's ruling of 2026-10-25 00:27Z (1): an amend the order as it stands makes
    risk-increasing where step 4's read did not is refused before the send, `409 conflict` with
    `Retry-After: 1` without `If-Match` and `412` with it, and the refusal is audited
    (`orders.amend`, the step and the reason named) and counted; the client sends the amend again
    and is judged afresh."""
    assert not _missing(
        _AMEND,
        "The refusal of an amend that the order as it stands makes risk-increasing, where the "
        "route's first read did not, is audited (`orders.amend`, denied, the step and the reason "
        "named: `class` and `reclassified`), and the client sends the amend again, judged afresh "
        "(the orchestrator's ruling of 2026-10-25 00:27Z (1))",
    )
    assert not _missing(
        _EXITS,
        "is refused before the send alike: `412` with `If-Match`, `409 conflict` with "
        "`Retry-After: 1` without; the refusal is audited (`orders.amend`, denied with its code, "
        "the step and the reason named in its detail: `class`, the class re-check, and "
        "`reclassified`, the class changed since step 4) and counted, and the client sends the "
        "amend again, judged afresh (the orchestrator's ruling of 2026-10-25 00:27Z (1))",
        "Every refusal, the unaudited ones too, is counted in "
        "`oms_exit_refused_total{operation,code}`",
    )


def test_the_exit_routes_declare_every_answer_their_routes_give() -> None:
    """The orchestrator's ruling of 2026-10-24 21:47Z (1) and vw3's gap of 22:11Z: `cancelOrder`
    declares the `500` its route answers for a fault the exit service raises, as `amendOrder`,
    whose route renders the same service, and `cancelAllOrders` (the ruling of 2026-10-25 00:27Z
    (3)), all through one shared `InternalError`, the registry's `internal_error`, which says what
    the shared renderer gives (00:36Z): no `instance`, the correlation id on `X-Correlation-Id`;
    `cancelAllOrders` declares its in-flight guard's `429`; and each declares step 1's `401` (no
    principal), the shared `Unauthorized`, as the orchestrator's security look on S4-D1b found it
    undeclared. Each of the three declares these statuses and no other."""
    declared = {
        name: set(_OPS[name]["responses"])
        for name in ("amendOrder", "cancelOrder", "cancelAllOrders")
    }
    assert declared == {
        "amendOrder": {
            *("202", "400", "401", "403", "404", "409", "412", "422", "429", "500", "501"),
            *("502", "503"),
        },
        "cancelOrder": {
            *("202", "400", "401", "403", "404", "409", "429", "500", "501", "502", "503"),
        },
        "cancelAllOrders": {"200", "400", "401", "403", "409", "429", "500", "501", "503"},
    }
    for name in declared:
        assert _answers(name)["401"] == "Unauthorized", name
    assert {_answers(name)["500"] for name in declared} == {"InternalError"}
    assert _answers("cancelAllOrders")["429"] == "RateLimited"
    fault = _COMPONENTS["responses"]["InternalError"]
    assert list(fault["content"]) == ["application/problem+json"]
    body = fault["content"]["application/problem+json"]
    assert body["schema"] == {"$ref": "#/components/schemas/Problem"}
    [example] = [shown["value"] for shown in body["examples"].values()]
    [entry] = [e for e in _SPEC["x-error-codes"] if e["code"] == "internal_error"]
    assert (entry["status"], entry["retryable"]) == (500, True)
    assert (example["code"], example["status"], example["title"]) == (
        "internal_error", 500, entry["title"],
    )  # fmt: skip
    assert example["type"] == "https://candleviewer.local/errors/internal_error"
    rendered = order_problem(OmsError("a fault no row names"))  # the shared renderer's 500
    assert json.loads(bytes(rendered.body)) == example and "instance" not in example
    described = _words(fault["description"])
    assert not _missing(
        described,
        "`internal_error`, retryable (the error-code registry)",
        "The problem names no internals and carries no `instance`, which no order route sets: the "
        f"request's correlation id rides the `{CORRELATION_HEADER}` response header",
        "On the exit routes (`amendOrder`, `cancelOrder`, `cancelAllOrders`) it is a fault the "
        "exit service raised, which also pages the operator",
    )
    assert "`instance` carries" not in described
    assert (
        "`429 rate_limited` with `Retry-After: 1` when the in-flight guard holds all its keys, or "
        "all the caller's share of them, nothing sent (24-internal-schemas.md section 8.4 step 9)"
        in _CANCEL_ALL
    )


def test_a_cancel_of_an_order_already_final_is_recorded_ahead_of_its_202() -> None:
    """The orchestrator's ruling of 2026-10-24 21:47Z (2), built in S4-C2b (`ALREADY_FINAL`): the
    user's cancel is the action even with nothing to send, and the `audit_outcome` enum has no
    `noop`, so it is recorded `success` with a reason of its own."""
    assert (
        "A cancel that finds its order already final, nothing to send, is the user's action all "
        "the same: `orders.cancel` with outcome `success` and reason `already_final`, written "
        "before its `202`, else `503 audit_unavailable` in its place (C-2.9; the "
        "`audit_outcome` enum has no `noop`; the orchestrator's ruling of 2026-10-24 21:47Z (2))"
        in _EXITS
    )
    assert ALREADY_FINAL == "already_final"
    enum = r"CREATE TYPE audit_outcome\s+AS ENUM \('success','failure','denied'\);"
    assert re.search(enum, _SCHEMA_DOC) is not None


def test_an_id_routes_malformed_id_and_step_2s_permission_sit_where_the_route_answers() -> None:
    """vw3's code look on S4-D1b, item 10: an id route answers an order id that is no UUID after
    step 1's principal and before step 2, unaudited, as `placeOrder`'s unreadable body; step 2
    checks `orders:write` alone, as no account is known yet, and the trade grant is step 4's
    (`can_trade` false is `403 account_scope_denied`)."""
    assert not _missing(
        _EXITS,
        "1. the principal, as the route's step 1; then, on an id route, the order's id: one that "
        "is not a UUID names no order, so it is `400 validation_failed` before step 2, "
        "unaudited, as `placeOrder`'s unreadable body is;",
        "2. RBAC: `orders:write` alone, `403 forbidden` without the permission, as no account is "
        "known yet: the trade grant is step 4's, read with the order (a view-only grant is `403 "
        "account_scope_denied` there) or, on `cancelAllOrders`, with the accounts its body lists;",
    )
    assert "`orders:write` with `requires_trade`" not in _EXITS


def test_a_protective_cancel_under_view_as_runs_as_the_viewer_in_the_targets_scope() -> None:
    """vw3's view-as look on S4-D2a, LOW-4 (the orchestrator's rulings of 2026-10-25 01:11Z (3)
    and 01:24Z): 22's protective writes name the cancels, protective whole through the C-2.6
    carve-out under `Forbidden`, where a cancel needs no `ArmToken`: a protective cancel runs as
    the viewer, with both the viewer's RBAC and the target's `x-rbac`, and in the hold in the
    viewer's own scope. 24's step 4 reads the target's trade grants as the viewer may act on them,
    never the viewer's own, and in the hold the viewer's own scope."""
    protective = _INFO.split("**Protective writes (C-2.6).**", 1)[1].split("* **Scope.**", 1)[0]
    assert not _missing(
        protective,
        "Among the writes the carve-out names are the cancels, `cancelOrder` and "
        "`cancelAllOrders`, protective whole (`ArmToken` lists the carve-out's full set: a cancel "
        "is never refused for want of the arm token, so the cancel routes do not declare it)",
        "both pass to their handlers, and a protective cancel runs as the viewer, admitted only "
        "when both the viewer's own RBAC and the target's `x-rbac` allow it, and in the hold in "
        "the viewer's own scope",
    )
    arm = _words(_COMPONENTS["parameters"]["ArmToken"]["description"])
    assert "cancels, `closePosition`, `closeAllPositions`" in arm  # the full set it lists
    assert "so the cancel and close routes do not declare it" in arm
    for name in ("cancelOrder", "cancelAllOrders"):
        refs = [param.get("$ref", "") for param in _OPS[name]["parameters"]]
        assert not [ref for ref in refs if ref.endswith("/ArmToken")], name
    assert not _missing(
        _EXITS,
        'Under view-as (`22-api-openapi.yaml` "View-as session", its protective writes) the '
        "scope is the target's trade grants as the viewer may act on them (the view-as guard's "
        "`scope_for_target`), never the viewer's own grants, as a protective write is admitted "
        "only when both the viewer's own RBAC and the target's `x-rbac` allow it; in the hold it "
        "is the viewer's own scope",
    )


def test_every_exit_500_pages_one_page_for_the_faults_class() -> None:
    """The orchestrator's ruling of 2026-10-25 02:50Z (2), made of the first fold's note: an exit
    route's `500` pages whatever raised it, by the fault's class alone, never its text, so 22's
    "which also pages the operator" holds for every one; `placeOrder`'s `500`, which pages only
    where its row does, is no longer the comparison (CR-S4D2A-08)."""
    described = _words(_COMPONENTS["responses"]["InternalError"]["description"])
    assert (
        "On the exit routes (`amendOrder`, `cancelOrder`, `cancelAllOrders`) it is a fault the "
        "exit service raised, which also pages the operator: every exit `500` pages, one page "
        "for the fault's class, never its text" in described
    )
    assert "00:36Z and 02:50Z (2))" in described
    assert "as `placeOrder`'s `500` does" not in described


def test_a_step_into_a_state_that_takes_no_amend_is_422_as_at_admission() -> None:
    """CR-S4D2A-02: the `409` and the `412` answer a step that leaves the order amendable; a step
    into a state that takes no amend meets the facade's state check, which comes before its
    version check, so it is `422 order_not_amendable`, as at admission, `If-Match` or not."""
    assert (
        "The `409` and the `412` answer a step that leaves the order amendable (a partial fill, "
        "another amend settled): a step that leaves it in a state that takes no amend (a fill "
        "that completes it, a cancel or another amend in flight) is `422 order_not_amendable`, "
        "as at admission, with `If-Match` or without." in _AMEND
    )
    assert (
        "The `412` and the `409` answer a step that leaves the order amendable: a step that "
        "leaves it in a state that takes no amend (a fill that completes it, a cancel or another "
        "amend in flight) is `422 order_not_amendable`, as at admission, with `If-Match` or "
        "without, as the facade checks the state before the version." in _EXITS
    )


def test_a_gone_row_an_already_final_cancel_and_a_refusals_detail_are_written_down() -> None:
    """CR-S4D2A-07: step 11 says that a row its re-read no longer finds is `409 conflict`, as
    `OrderExits.amend` answers it; 15.5's reasons name `already_final` and a refusal's detail
    keys, `step` (`ExitStep`'s six, the amend route's `body` and `arm` among them, S4-D2b) and the
    class re-check's `reason` (`RECLASSIFIED`), beside the record's own `reason`, its code."""
    assert "a row that read no longer finds is `409 conflict`, nothing sent." in _EXITS
    assert not _missing(
        _RECORDS,
        "A cancel that finds its order already final, nothing to send, is `orders.cancel` with "
        "outcome `success` and reason `already_final`, written before its `202` (§8.4).",
        "A refusal's detail names, beside `code`, the step that refused it where one did "
        "(`step`: the route's `key`, `replay` or `guard`, and an amend's `body` or `arm` too, or "
        "`class`, step 11's class re-check), and the class re-check's refusal its cause too "
        "(`reason`: `reclassified`, the class changed since step 4): the record's own `reason` "
        "is the code, `detail.reason` the cause.",
    )
    assert (ALREADY_FINAL, RECLASSIFIED) == ("already_final", "reclassified")
    steps = {"key", "replay", "guard", "class", "body", "arm"}
    assert set(get_args(ExitStep.__value__)) == steps


def test_the_change_log_records_the_amend_judged_as_it_stands_and_the_exit_answers() -> None:
    """CR-S4D2A-04: 19 is the contract change log, so S4-D2a's changes to 8.4, 15.5 and 22 have
    an entry of their own, which supersedes 19.33's "`If-Match` alone carries a version"."""
    entry = _words(_INTERNAL_DOC.split("\n### 19.35 2026-10-25 — §8.4, §15.5: ", 1)[1])
    assert not _missing(
        entry,
        "an amend judged on the order as it stands, and the exit routes' answers (E29-T04, #913)",
        "issues/913#issuecomment-6381292953) Q5, as amended for SEC-S4C2B-01 on 2026-10-24)",
        "and sent at the version it was judged at, which `If-Match`, when given, must name",
        "`409 conflict` with `Retry-After: 1`, and `412` for the client's own tag alone",
        "one into a state that takes no amend is `422`, as at admission; a row no longer there "
        "is `409 conflict`",
        'This supersedes §19.33\'s "`If-Match` alone carries a version to the facade".',
        "§8.4 steps 1, 2, 4, 5 and 11:",
        "audited `orders.amend` denied with `step` `class` and `reason` `reclassified`",
        "`amendOrder` and `cancelOrder` gain `401` and `500`, and `cancelAllOrders` `401`, "
        "`429` and `500`. The three `500`s are one new response, `InternalError`",
        "every exit `500` pages, one page for the fault's class",
    )
