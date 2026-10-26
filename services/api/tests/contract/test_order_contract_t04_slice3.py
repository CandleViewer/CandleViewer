"""Contract (#913, E29-T04 slice 3): the texts that sub-slices B to G code against, read from 22,
21 (3.10.1, 10.7, 12, 13.1), 20 (6.2, 7.2, 12.1), 23 (6.4), 24 (8.4, 9.3, 15.5) and the
regenerated models, never from a copy: the orchestrator's slice-3 rulings of 2026-10-23 (Q2 to
Q12, Q16, Q18, Q20), with the code lens's findings on them folded (CR-S3A-01 to CR-S3A-15, and
CR-S3N-01 to CR-S3N-09 on the notes of 20, 21, 23 and 24)."""

from __future__ import annotations

import ast
import inspect
import re
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from candleviewer import oms_wiring
from candleviewer.account_health_wiring import TRACKING_FAULT_AFTER_S
from candleviewer.accounts.verification import Refusal
from candleviewer.api._generated import openapi_models as rest
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.api.orders import make_orders_router
from candleviewer.audit.machine_events import APPEND_FAILURE_COOLDOWN_S, MachineEventWrongLoop
from candleviewer.audit.writer import AuditUnavailable, AuditWriterWrongLoop
from candleviewer.exchange.bybit.key_info import refusal
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.oms import submit
from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms_lane import BLOCK_TIMEOUT_S, HOP_TIMEOUT_S, LANE_JOIN_S, LANE_START_S
from candleviewer.oms_wiring import (
    ENVIRONMENT_FENCE_GRACE_S,
    ENVIRONMENT_LOCK_NAMESPACE,
    ENVIRONMENT_LOCK_TIMEOUT_S,
    LANE_AUDIT_PAGE_S,
    LANE_AUDIT_STOP_S,
    LANE_STALE_S,
    LANE_TICK_S,
    LANE_WAL_PREFIX,
    REFERENCE_DEMAND_MAX,
    REFERENCE_DEMAND_NEW,
    REFERENCE_DEMAND_TTL_S,
    REFERENCE_DEMAND_WINDOW_S,
    SWEEP_MAX_FAILURES,
    SWEEP_RETRY_S,
    SWEEP_STATEMENT_TIMEOUT_MS,
    SYSTEM_ACTOR,
    EnvironmentLocked,
    OmsAudit,
    OmsBounds,
    OmsRuntime,
    OrderStateFeed,
    ReferenceDemand,
    ServedGate,
    UnclaimedMachineEvents,
    environment_lock_key,
)
from candleviewer.settings import (
    ACCOUNT_DOWN_MAX_S,
    OMS_AFTER_ANCHOR_S,
    OMS_STOP_RESERVE_S,
    TEARDOWN_BUDGET_S,
    Settings,
)
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT, CV_PERSIST_TIMEOUT
from candleviewer.storage.repositories.session_lock_sqlalchemy import KEEPALIVE, STALE_HOLDER_S
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from candleviewer.ws.topics import MACHINE_KINDS
from tests.openapi_helpers import deref

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_RESPONSES: dict[str, Any] = _SPEC["components"]["responses"]
_PLACE: Any = _SPEC["paths"]["/orders"]["post"]
_ARCH, _SCHEMA_DOC, _WS_DOC, _INTERNAL_DOC = (
    (OPENAPI_SPEC_PATH.parent / name).read_text(encoding="utf-8")
    for name in (
        "20-architecture.md",
        "21-database-schema.md",
        "23-ws-protocol.md",
        "24-internal-schemas.md",
    )
)


def _words(text: str) -> str:
    """A description on one line: a YAML block keeps its line breaks, a phrase may span two."""
    return " ".join(text.split())


def _between(text: str, start: str, end: str) -> str:
    return _words(text.split(start, 1)[1].split(end, 1)[0])


def _missing(text: str, *statements: str) -> list[str]:
    return [statement for statement in statements if statement not in text]


def _validator(name: str) -> Draft202012Validator:
    schema = deref(_SPEC, {"$ref": f"#/components/schemas/{name}"})
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


_PLACE_TEXT = _words(_PLACE["description"])
_ROUTE = _between(_INTERNAL_DOC, "**The route (E29-T04 slice 3;", "**8.4.1 ")
_RUNTIME = _between(_ARCH, "**OMS runtime (E29-T04 slice 3, #913).**", "**Startup self-check")
_UNRESOLVED = {"validated", "submitting", "unknown", "quarantined"}  # Q2's B1 states


def test_an_acceptance_says_whether_its_order_is_still_reconciling() -> None:
    """Q2: a required boolean, true while the order is unresolved, a first answer included; as of
    the answer, and false for every other state, `held` included (CR-S3A-11)."""
    schema = _SCHEMAS["OrderAcceptance"]
    member = schema["properties"]["reconciling"]
    assert (schema["required"][-1], member["type"]) == ("reconciling", "boolean")
    assert not _missing(
        _words(member["description"]),
        "True when, as of the answer, the answered order is unresolved",
        "or its state could not be read; a first answer included",
        "False for every other state, `held` included.",
    )
    states = set(_SCHEMAS["OrderLifecycleState"]["enum"])
    assert _UNRESOLVED < states and "held" in states - _UNRESOLVED
    assert "reconciling" not in states
    field = rest.OrderAcceptance.model_fields["reconciling"]
    assert (field.annotation, field.is_required()) == (bool, True)
    examples = _PLACE["responses"]["202"]["content"]["application/json"]["examples"]
    validator = _validator("OrderAcceptance")
    for example in examples.values():
        body = example["value"]
        validator.validate(body)
        rest.OrderAcceptance.model_validate(body)  # the generated model takes it too
        group = body["trade_group"]
        orders = [body["order"]] if group is None else group["legs"][0]["order_details"]
        assert body["reconciling"] is any(o["lifecycle_state"] in _UNRESOLVED for o in orders)
    unknown = examples["reduceOnly"]["value"]
    with pytest.raises(ValidationError, match="'reconciling' is a required property"):
        validator.validate({key: value for key, value in unknown.items() if key != "reconciling"})
    with pytest.raises(ValidationError, match="is not of type 'boolean'"):
        validator.validate(unknown | {"reconciling": "true"})


def test_the_oms_flag_refuses_only_new_admissions_with_a_reasonless_403() -> None:
    """Q3, Q18: after the lookup, before the switches; owned, with a removal ticket (C-4.13); its
    view takes no principal and, like `trading.live_enabled`'s, is off while unread (21 10.7)."""
    assert not _missing(
        _PLACE_TEXT,
        "while off, refuses a new admission that opens or increases exposure with "
        "`403 trading_disabled` and no `reason`",
        "neither a create a restart resumes nor a cancel is refused by it",
    )
    forbidden = _words(_RESPONSES["Forbidden"]["description"])
    assert "flag, while off, also refuses with `trading_disabled` and no `reason`" in forbidden
    general = _words(_SPEC["info"]["description"])
    exposure = "`placeOrder` and an amend that increases exposure"  # slice 4 ruling Q10
    assert f"(on {exposure} the `trading.oms_enabled` flag, then live trading not" in general
    order = general.split("**Order of the checks on an order submit or amend (E29-T04).**")[1]
    item = _between(_INTERNAL_DOC, "\n1. After authentication, CSRF", "\n2. ")
    for text in (order, item):  # 22's order and 24's step 1 agree
        at = [text.index(s) for s in ("lookup", "`trading.oms_enabled` flag", "live trading")]
        assert at == sorted(at)
        assert f"the `trading.oms_enabled` flag ({exposure})" in text
    section = _SCHEMA_DOC.split("### 10.7 Feature flags", 1)[1].split("### 10.8 ", 1)[0]
    [row] = [line for line in section.splitlines() if line.startswith("| `trading.oms_enabled`")]
    cells = "|".join(cell.strip() for cell in row.strip("|").split("|")[1:])
    assert cells == "boolean|`false`|New OMS orders; owner @basiltt, removal #4227|`all_roles`"
    assert not _missing(
        _words(section),
        "the insert-only `ensure` of a demo process seeds it `true`, and that of a live or "
        "testnet process `false`",
        "share a database the first `ensure` decides",
        "so an override written for it changes nothing, as for `desktop.backend_connection`",
        "is off while unread: until its first read it answers off",
    )
    switches = _between(_INTERNAL_DOC, "**`TradingSwitches`", "**A refused")
    assert "view that is off while unread (`21-database-schema.md` §10.7)" in switches


def test_every_not_ready_case_answers_one_503_and_the_fake_backend_a_501() -> None:
    """Q7, Q8: the runtime, the catalogue, an unmeasured clock; `clock_drift` stays measured; the
    runtime's answer, like the 501, is counted, never audited, so it never turns into a 503
    `audit_unavailable`; 24's pipeline item names its own `oms_not_ready` cases."""
    entry = next(e for e in _SPEC["x-error-codes"] if e["code"] == "oms_not_ready")
    assert (entry["status"], entry["retryable"]) == (503, True)
    assert ERROR_META[ErrorCode("oms_not_ready")].title == entry["title"]
    assert re.search(r"(?i)\bbybit\b|\d{4,}", entry["title"]) is None  # no vendor, no raw code
    code_title = ("oms_not_ready", entry["title"])
    body = _RESPONSES["ServiceUnavailable"]["content"]["application/problem+json"]["examples"]
    body = body["omsNotReady"]["value"]
    _validator("Problem").validate(body)
    assert (body["code"], body["title"], body["retry_after_seconds"]) == (*code_title, 5)
    assert OmsNotReady().retry_after_s == body["retry_after_seconds"]  # the code's default
    assert _PLACE["responses"]["501"] == {"$ref": "#/components/responses/NotImplemented"}
    assert not _missing(
        _PLACE_TEXT,
        "the request is refused with `503 oms_not_ready` and `Retry-After`, before anything is "
        "recorded or sent and with no key bound",
        "while no instrument catalogue is composed or the exchange clock guard has not taken",
        "`clock_drift` is answered for a measured halt only (above)",
        "(the fake backend) answers `501 not_implemented` instead",
        "The runtime's answer is not audited, as the `501` is not, but counted, so it is never "
        "turned into `503 audit_unavailable`",
    )
    item = _between(_INTERNAL_DOC, "\n2. The OMS refuses while", "\n3. ")  # the pipeline's own
    assert "and an instrument catalogue not composed, are `503 oms_not_ready` instead" in item


def test_24_gives_the_routes_checks_in_the_ruled_order_and_audits_each_refusal() -> None:
    """The brief's order; Q9: a lost record is `403` up to existence, then 503 (C-2.9); step 3's
    `oms_not_ready`, like the 501, is counted, not audited; a body with no account id is a 400."""
    section = _INTERNAL_DOC.split("**The route (E29-T04 slice 3;", 1)[1].split("\n\nEach ", 1)[0]
    heads = re.findall(r"^\d+\. ([^:,(;]+)", section, re.MULTILINE)
    assert [head.strip() for head in heads] == [
        *("the principal", "RBAC", "the OMS runtime", "the account's existence", "the arm token"),
        *("`Idempotency-Key`", "the 24 h record", "the anchor's lookup"),
        *("the `trading.oms_enabled` flag", "the switches", "the body", "`submit`"),
    ]
    assert not _missing(
        _ROUTE,
        "(https://github.com/CandleViewer/CandleViewer/issues/913#issuecomment-6355322724)",
        "with `requires_trade`, so a Manager needs a grant that allows trading",
        "is `400 validation_failed` before this step, unaudited, as the API's request-validation "
        "answers are: there is no account to scope it",
        "with no oracle",
        "`503 oms_not_ready` with `Retry-After`",
        "`algo_unsupported`, until E32 and E34",
        "shielded from the client's disconnect and from the request's deadline",
        "at most `CV_OMS_DRAIN_S`",
        "Each refusal from step 2 on, the `501` and the `oms_not_ready` of steps 3 and 10 aside, "
        "is audited",
        "steps 2 and 4 as `rbac.denied`, the gate's as `account.disabled_by_policy`",
        "every other as `orders.submit` with outcome `denied` and its code",
        "Step 3's `oms_not_ready` is not audited, as the `501` is not, but counted "
        "(`oms_submit_rejected_total`",
        "so it always wins over `audit_unavailable`, and a client retrying through a startup adds "
        "no audit rows",
        "any later refusal whose record cannot be written answers `503 audit_unavailable`",
    )
    assert submit.SUBMIT_ACTION == "orders.submit" and "denied" in _SCHEMAS["AuditOutcome"]["enum"]
    assert "the `501` and the runtime's `oms_not_ready` aside (below)" in _PLACE_TEXT
    assert "stays `403` when its record cannot be written; any later refusal" in _PLACE_TEXT


def test_live_needs_both_preconditions_and_the_switches_run_live_b18_gate() -> None:
    """Q4, Q5: the setting and the flag; the B18 interim and a missing bundle, announced as interim
    ports, never on the anonymous `/readyz`; synchronous (C-2.21)."""
    assert not _missing(
        _PLACE_TEXT,
        "the `CV_TRADING_LIVE_ENABLED` setting and the `trading.live_enabled` flag",
        "the B17 live-enablement gate stays the user-facing truth",
    )
    assert not _missing(
        _RUNTIME,
        "the `CV_TRADING_LIVE_ENABLED` setting and the `trading.live_enabled` flag",
        "Until E39-S03 the B18 kill switch is an interim that admits",
        '`oms_interim_ports{port="kill_switch"}` at 1 (§12.1)',
        "The startup announces a missing bundle as it does an interim port, with a WARNING and "
        '`oms_interim_ports{port="machine_event_sink"}` at 1 (§12.1)',
    )
    switches = _between(_INTERNAL_DOC, "**`TradingSwitches`", "**A refused")
    assert "live trading enabled, then the B18 kill switch, then the order-entry gate" in switches
    row = _between(_ARCH, "| OMS | `oms_interim_ports{port}` |", "\n")
    assert not _missing(
        row,
        "slice 3 ruling Q5: `kill_switch`, the B18 kill switch until E39-S03",
        "slice 3: `machine_event_sink`, B1's `machine_events` sink while no statechart persistence",
        "Status of these two: served since #913 slice 3 (sub-slices B to G merged)",
    )


def test_a_new_holder_waits_out_the_fence_and_a_fenced_runtime_admits_nothing_new() -> None:
    """SEC-S3L2-01, -02 (the Fable lens at 864fa082): 20 states the fencing grace from the code's
    own names and bound, and the fence at the route's step 3 and in the switches; 24 gives the
    switches' first refusal and both routes' step 3; the E29 model's §12.2 the grace's residual."""
    assert not _missing(
        _RUNTIME,
        "The route's step 3 reads the runtime's readiness, `degraded` once the lock is lost, "
        "while the exit routes read its state, and the fence is the switches' first refusal "
        "(`TradingSwitches`, 24 §8.4), so a submit any caller makes on the lane, a resumed create "
        "and a risk-increasing amend included, is refused `oms_not_ready` there too (SEC-S3L2-02).",
        f"A process that takes the lock waits {ENVIRONMENT_FENCE_GRACE_S:g} s from then "
        "(`ENVIRONMENT_FENCE_GRACE_S`, a tick and the watchdog's bound, step 1's waits counting "
        "toward it) before its startup sweep, and so before its first admit: a previous holder "
        "whose session ended has fenced itself by then, so the two never sweep or admit at once "
        "(SEC-S3L2-01).",
    )
    switches = _between(_INTERNAL_DOC, "**`TradingSwitches`", "**A refused")
    assert not _missing(
        switches,
        "the first refusal wins: the environment's lock held, then live trading enabled",
        f"the binding refuses every order first, `{OmsNotReady.__name__}` "
        "(`503 oms_not_ready`), whatever the rest say",
    )
    placed = _between(_INTERNAL_DOC, "\n3. the OMS runtime: none composed", "\n4. ")
    assert "or one whose environment's lock is lost (its readiness, SEC-S3L2-02)" in placed
    exits = _between(_INTERNAL_DOC, "\n3. the OMS runtime, as the route's step 3", "\n4. ")
    assert "by its state, so a lost environment lock refuses no exit (C-2.6)" in exits
    threat = OPENAPI_SPEC_PATH.parents[1] / "security" / "threat-models" / "E29-oms.md"
    residuals = _between(
        threat.read_text(encoding="utf-8"), "### 12.2 Accepted residual risks", "### 12.3"
    )
    assert not _missing(
        residuals,
        "**The environment lock's fencing grace (#913 L2, SEC-S3L2-01).**",
        f"A process that takes the lock waits those {ENVIRONMENT_FENCE_GRACE_S:g} s "
        "(`ENVIRONMENT_FENCE_GRACE_S`) before its startup sweep and its first admit",
    )


def test_the_e29_model_gives_the_fencing_grace_an_owner_a_ticket_and_a_review_date() -> None:
    """CR-S3L2X-07: §12.2's fencing-grace residual carries what the table's rows carry: its level,
    its owner, its ticket and a review date."""
    threat = OPENAPI_SPEC_PATH.parents[1] / "security" / "threat-models" / "E29-oms.md"
    residuals = _between(
        threat.read_text(encoding="utf-8"), "### 12.2 Accepted residual risks", "### 12.3"
    )
    grace = residuals.split("**The environment lock's fencing grace (#913 L2, SEC-S3L2-01).**")[1]
    assert (
        "Like the rows above it has a level, an owner, a ticket and a review date: Low; Owner/PO; "
        "E29-T04;" in grace
    )
    assert re.search(r"review by \d{4}-\d{2}-\d{2}", grace)


def test_20_says_a_dead_lane_keeps_the_environments_lock_until_the_process_exits() -> None:
    """CR-S3L2X-07: nothing on a lane that has died can release the lock, so 20 says it is held
    until the process exits, a second process refused until then."""
    assert (
        "A lane that has died keeps the lock until the process exits: its watchdog ticks no more, "
        "and the stop's release, a call on that lane, is refused, so nothing ends the lock's "
        "session before the exit does, and a second process is refused until then (CR-S3L2X-07)."
        in _RUNTIME
    )


def test_20_pages_a_lane_with_no_reader_and_an_unanswered_lock_and_closes_a_raced_compose() -> None:
    """SEC-S3L2-04 to -06 (the Fable lens at 864fa082): 20 says the serving loop reads the lane's
    state itself, a heartbeat's end pages, the unanswered lock pages once while the asking goes
    on, and nothing a composition built outlives a stop or a cancelled start that races it."""
    assert SWEEP_MAX_FAILURES == 5  # "the fifth"
    assert not _missing(
        _RUNTIME,
        "The fifth unanswered ask in a row (`SWEEP_MAX_FAILURES`), the start's own counted, is "
        "logged CRITICAL and paged once, and the asking goes on (SEC-S3L2-06).",
        f"The serving loop reads that state itself every {LANE_STALE_S:g} s, so a dead or wedged "
        "lane pages with nothing else reading it, and a heartbeat that ends on an error is logged "
        "CRITICAL (`oms_lane_heartbeat_ended`) and paged at once (SEC-S3L2-04).",
    )
    lane = _between(_ARCH, "**The order lane (29 CV-C13; #913 slice 3 L1).**", "**Live trading")
    assert (
        "A composition hands what it built to the runtime under a lock its stop takes too, so a "
        "stop that begins as one ends either takes it and closes it, or is seen by it, which then "
        "closes it itself, and a start cancelled once it has ended closes what was handed over: "
        "nothing composed outlives a stop or a cancelled start (SEC-S3L2-05)." in lane
    )


def test_20_starts_the_oms_after_account_health_and_sweeps_before_ready() -> None:
    """Q7, Q20: the sweep's steps in order, per environment, `ready` last, never before the flag
    views have read; Q6: the sink, keyed to the process environment; an anonymous `oms` check."""
    section = _ARCH.split("**OMS runtime (E29-T04 slice 3, #913).**", 1)[1].split("\n\nA ", 1)[0]
    steps = re.findall(r"^\d\. (.*)$", section, re.MULTILINE)
    keys = ("`CV_OMS_STARTUP_WAIT_S`", "`void_orphans`", "hydrates", "abandons", "sets `ready`")
    assert [key in step for key, step in zip(keys, steps, strict=True)] == [True] * 5
    assert "the first read of the two flag views" in steps[0]
    assert "and never goes on without it, so `ready` implies the flags are read" in steps[0]
    assert "for each account of the process environment, never for every account" in steps[1]
    assert "include the disabled and soft-deleted ones" in steps[1]
    assert "at most `MAX_MACHINES`; past that it pages and `ready` is refused" in steps[2]
    assert "nothing serves it until they land" not in _RUNTIME  # #913 S4-G1: as built
    assert not _missing(
        _RUNTIME,
        "Status: this text, down to the startup self-check, is as built by #913 slice 3 "
        "(sub-slices B to H): `create_app()` builds the runtime on the real backend "
        "(`build_oms_runtime`, `oms_wiring.py`; its order lane is `oms_lane.py`), and "
        "`placeOrder` and slice 4's exit routes (`cancelOrder`, `amendOrder`, "
        "`cancelAllOrders`) are served over it.",
        "The lifespan starts the runtime after the account health runtime, then E29-T05's",
        "`placeOrder` answers `503 oms_not_ready` with `Retry-After`",
        "must fit a deploy's 60 s `/readyz` smoke window",
        "`/readyz` carries an `oms` check that gives the runtime's state and nothing else: `ok` "
        "once `ready`; until then it fails, its detail `starting` while the sweep runs, or "
        "`degraded` once the runtime will not get ready",
        "`/readyz` is anonymous, so the check names no posture",
        "That stop is the lifespan's, run before `Supervisor.stop_all`, not the supervised OMS "
        "module's, but it keeps within that module's 15 s grace",
        "in a demo process (a testnet one fails closed first, above) whatever "
        "`CV_TRADING_LIVE_ENABLED` says, and in a live process only while that setting is off",
        "A live process with the setting on and no bundle fails closed",
        "It never uses an in-memory sink",
    )
    assert "no_persistence_bundle" not in _ARCH and "kill_switch=interim" not in _ARCH


def test_20_declares_the_oms_settings_within_the_bounds_the_code_holds() -> None:
    """The code's defaults; the ranges keep the stop, command and stuck bounds `OmsBounds` holds,
    the stop request's bound named where its setting is, and the drain inside the module's grace."""
    section = _ARCH.split("### 7.2 Configuration model", 1)[1].split("### 7.3 ", 1)[0]
    cells = [[cell.strip() for cell in line.strip("|").split("|")] for line in section.split("\n")]
    rows = {row[0].strip("`"): row[1:] for row in cells if len(row) == 5 and row[0][:4] == "`CV_"}
    expected = {
        "CV_OMS_SUBMIT_TIMEOUT_MS": ["int", "`5000`", "process"],
        "CV_OMS_INFLIGHT_STUCK_S": ["float", "`30`", "process"],
        "CV_OMS_STARTUP_WAIT_S": ["float", "`30`", "process"],
        "CV_OMS_DRAIN_S": ["float", "`10`", "process"],
        "CV_TRADING_LIVE_ENABLED": ["bool", "`false`", "process"],
    }
    assert {key: rows[key][:3] for key in expected} == expected
    bounds = OmsBounds.from_settings(Settings())
    assert (bounds.submit_timeout_s * 1000, bounds.stuck_after_s) == (5000, 30)
    assert not _missing(
        rows["CV_OMS_SUBMIT_TIMEOUT_MS"][3],
        "(24 §8.4); 1000-6000, so 3 ",
        "+ `CV_OMS_SUBMIT_TIMEOUT_MS` ≤ bound \N{MINUS SIGN} 1 s (the margin is clock skew "
        "+ commit latency): an entry's stop request, answered within",
        "lands inside 10 s, the stop request's bound (`oms_wiring.STOP_REQUEST_BOUND_S`",
        "with B1's `CV_COMMAND_TIMEOUT` ≤ it for an attach)",
    )
    top = OmsBounds.from_settings(Settings(oms_submit_timeout_ms=6000, oms_inflight_stuck_s=120))
    assert 3 * CV_PERSIST_TIMEOUT + top.submit_timeout_s == top.stop_request_s - 1 == 9
    assert CV_COMMAND_TIMEOUT <= top.stop_request_s and top.submit_timeout_s < CV_COMMAND_TIMEOUT
    assert bounds.after_anchor_s - bounds.submit_timeout_s == OMS_AFTER_ANCHOR_S == 12
    assert "(submit + 12 s), ≤ 120" in rows["CV_OMS_INFLIGHT_STUCK_S"][3]
    rules = _between(_INTERNAL_DOC, "**The pipeline's own rules", "**8.4.1 ")
    assert not _missing(
        rules,
        "the create's answer 6 s (it must outlast the command port's submit deadline, "
        "`CV_OMS_SUBMIT_TIMEOUT_MS`; the default adds 1 s for B1's turn, and the pipeline refuses "
        "a wait not above the deadline)",
    )
    assert bounds.place_wait_s - bounds.submit_timeout_s == 1  # B1's turn, past the deadline
    assert rows["CV_OMS_STARTUP_WAIT_S"][3].endswith("(§6.2); 5-45")  # inside the 60 s smoke
    assert "1-10, leaving ≥ 5 s of the OMS's 15 s grace" in rows["CV_OMS_DRAIN_S"][3]
    assert 10 + OMS_STOP_RESERVE_S == TEARDOWN_BUDGET_S  # the module's grace, 5 s left of it


def test_a_refused_credential_fails_closed_for_the_process_until_a_recorded_pass() -> None:
    """Q10 and its rider: an unlisted code or none is `unknown_key`, stricter than the self-check
    and in memory only; a recorded pass is Q10's re-read; the durable step is #4243."""
    rule = _between(_INTERNAL_DOC, "**A refused credential (§8.6 `AUTH_ERROR`;", "**8.4.1 ")
    table = {int(code): why for code, why in re.findall(r"`(\d{5})` `([a-z_]+)`", rule)}
    assert {code: refusal(map_ret_code(code, "")) for code in table} == {
        code: (why, code) for code, why in table.items()
    }
    assert set(table.values()) == {member.value for member in Refusal}
    assert refusal(map_ret_code(10004, "")) is None  # a refused signature: no verdict
    assert not _missing(
        rule,
        "a code outside it, `10004` among them, or none is `unknown_key`, fail closed",
        "stricter than the self-check, which holds a refused signature inconclusive (SR-E27-18), "
        "because an order cannot go on with a key it has not verified, and it holds in memory only",
        "no later order on the account is admitted in this process until a recorded pass",
        "clears it (ruling Q10's re-read)",
        "it pages the Owner",
        "is #4243, a follow-up of #913",
    )
    gate = _between(_INTERNAL_DOC, "**8.4.1 Account checks", "### 8.5 ")
    assert "whose durable reaction is #4243" in gate


def test_an_algo_waits_for_its_epics_and_held_rows_are_scanned() -> None:
    """Q12 and Q16: no index for `held` now, and 21 says the read scans for it. Q11's `ETag` is
    sent since slice 4 (`test_order_contract_t04_slice4.py`)."""
    assert "is refused with `validation_failed` / `algo_unsupported`" in _PLACE_TEXT
    table = _SCHEMA_DOC.split("### 13.1 Postgres", 1)[1].split("### 13.2 ", 1)[0]
    [row] = [line for line in table.splitlines() if line.startswith("| 49  |")]
    assert "none for `held`" in row and "once per boot, scans for `held`" in row
    assert "no index for `held` orders, which row 49 reads once per boot" in _words(table)


def test_a_replayed_429_or_502_declares_its_replay_header() -> None:
    """22's Idempotency section: the `429` and `502` a recorded order answers are replayed with
    `Idempotency-Replayed: true`, so `placeOrder` declares that header on both. The `502` is the
    shared `OrderExchangeError`, whose every route takes a key, so the header is declared there
    (#913 slice 3D2's security lens); its body stays `OrderExchangeProblem`, the code only."""
    replayed = {"$ref": "#/components/headers/IdempotencyReplayed"}
    assert _PLACE["responses"]["429"]["headers"]["Idempotency-Replayed"] == replayed
    assert _PLACE["responses"]["502"] == {"$ref": "#/components/responses/OrderExchangeError"}
    gateway = _RESPONSES["OrderExchangeError"]
    assert gateway["headers"]["Idempotency-Replayed"] == replayed
    schema = gateway["content"]["application/problem+json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/OrderExchangeProblem"}
    assert "carries `Idempotency-Replayed: true`" in _words(gateway["description"])
    for path_item in _SPEC["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            if operation["responses"].get("502") == _PLACE["responses"]["502"]:
                parameters = str(operation.get("parameters", []))
                assert "IdempotencyKey" in parameters, operation["operationId"]


def test_the_flag_is_narrower_than_the_gate_and_the_security_lens_nits_are_written() -> None:
    """The orchestrator's ruling on SEC-S3A-01 (2026-10-23): the flag gates admission, not
    mounting, and only what opens or increases exposure, so an order whose body says
    `reduce_only` passes it (C-4.14, C-2.6); the gate (24 8.10), which takes such an order, and
    the switches still do. SEC-S3A-02 to -05: `/metrics`' reach, the flag write's propagation
    bound, which `502` is stored, the sink's rows never restored from; and a stale ticker."""
    assert not _missing(
        _PLACE_TEXT,
        "It is narrower than the order-entry gate (`24-internal-schemas.md` section 8.10): an "
        "order whose body says `reduce_only` passes it, read from the one parsed body the strict "
        "read validates and only as a JSON `true`, since a rollout flag gates no protective path "
        "(C-4.14, C-2.6), while the gate and the switches below still take that order and the "
        "server still classifies it by its effect (SR-E29-01, above).",
        "The route is mounted whatever the flag says: the flag gates admission, not mounting.",
    )
    forbidden = _words(_RESPONSES["Forbidden"]["description"])
    assert (
        "an admission that opens or increases exposure only: an order whose body says "
        "`reduce_only` passes it" in forbidden
    )
    step = _between(_INTERNAL_DOC, "\n9. the `trading.oms_enabled` flag", "\n10. ")
    assert (
        "It is narrower than the gate: an order whose body says `reduce_only` passes it (C-4.14, "
        "C-2.6), while the gate (§8.10) and step 10's switches still take that order and the "
        "pipeline still classifies it by its effect (SR-E29-01)." in step
    )
    assert (
        "The flag reads `reduce_only` from the one parsed body that step 11 validates, and only "
        "a JSON `true` passes it." in step
    )
    section = _words(_SCHEMA_DOC.split("### 10.7 Feature flags", 1)[1].split("### 10.8 ", 1)[0])
    assert not _missing(
        section,
        "of those only the ones that open or increase exposure: an order whose body says "
        "`reduce_only` passes it, since a rollout flag gates no protective path (C-4.14, C-2.6), "
        "though the order-entry gate still takes that order",
        "A replay, a create a restart resumes and a cancel never meet it",
        "The route is mounted whatever the flag says.",
        "and off again whenever a read fails, until one answers",
        "A write reaches the process that makes it at once, through the writer's hook (else on its "
        "own poll), and every other process sharing the database within `FLAG_POLL_S` (5 s) plus "
        "one read",
    )
    architecture = _words(_ARCH)
    assert (
        "never gets ready (dashboard); read on `/metrics`, whose reach is the SR-046 ACL and the "
        "private bind, not authentication" in architecture
    )
    assert not _missing(
        _RUNTIME,
        "No `machine_events` row carries a MAC, the standalone sink's included",
        "None is ever a restore source: hydration rebuilds each order's machine from its "
        "`order_events` and its row",
    )
    gateway = _words(_RESPONSES["OrderExchangeError"]["description"])
    assert "today only by `placeOrder`'s anchor" in gateway
    sizing = _between(_INTERNAL_DOC, "### 9.3 Sizing algorithm", "**9.3.1 Stop resolution.**")
    assert not _missing(
        sizing,
        "a symbol the stream holds stale has neither",
        "a stale price never sizes, caps or checks a market order",
    )


def test_20_says_what_a_second_oms_process_and_a_testnet_one_do() -> None:
    """CR-S3N-01, -03, -06, -08, -09a: the one-process presumption and what breaks it as the code
    does (the sweep voids an unsent entry's attach rows, and its KILL and the first process's
    `SEND` race on the order row), the lock that enforces it (SEC-S3N-01, #913 L2) from the code's
    own names and bound, a testnet process's `/readyz`, and the loop of the facade."""
    assert not _missing(
        _RUNTIME,
        "builds it in its `start()`, on the order lane (below), and unwires it in its `stop()`.",
        "`ready` is never set early. Until it is set, `placeOrder` answers `503 oms_not_ready` "
        "with `Retry-After`. The sweep, its wait included, must fit a deploy's 60 s `/readyz` "
        "smoke window (`tools/ci/deploy_dev.py`), so `CV_OMS_STARTUP_WAIT_S` is at most 45 s. "
        "The sweep and the facade presume one OMS process per environment and database.",
        "A second one, such as a deploy overlapping on another host, would sweep an entry the "
        "first has recorded and not yet sent: its step 2 voids the entry's attach rows, so 21 "
        "§3.3.11's "
        '"no request can send any more" stops holding, and its step 4 KILL and the first '
        "process's `SEND` race on the order row's compare-and-set.",
        "If the KILL commits first, the `SEND` meets a row that has moved on and nothing is sent "
        "(24 §8.4).",
        "If the `SEND` commits first, the entry is sent with its native stop on the create "
        "(C-2.6) while its record stays `void`, a state `trg_rs_guard` never lets a row leave, "
        "so 24 §8.5 step 5 has no record to restore the position's stop against.",
        "Its step 3 also resumes the first's in-flight `submitting` creates under their own "
        '`orderLinkId`s (24 §8.2 "Recovery", C-2.10).',
        "The runtime enforces the presumption (SEC-S3N-01, #913 slice 3 L2): before its facade "
        "or any machine exists, `start()` takes the environment's Postgres advisory lock, "
        "`pg_try_advisory_lock` on the signed 64-bit key BLAKE2b gives for "
        f"`{ENVIRONMENT_LOCK_NAMESPACE.decode()}` and the environment "
        f"(`oms_wiring.{environment_lock_key.__name__}`), outside the 32-bit range every "
        "`hashtext` key lies in, on a connection of the OMS pool's own, and holds it for the "
        "facade's life, releasing it in `stop()` after every other closer.",
        f"it fails closed (`{EnvironmentLocked.__name__}`, logged CRITICAL as "
        "`oms_runtime_failed_closed` with `phase` `environment_lock`, and paged), sweeps and "
        "hydrates nothing, is never `ready` and is not asked again",
        "That connection is one of the pool's 15 (`pool_size` 10, `max_overflow` 5), taken for the "
        "process's life; the pool's dispose at the stop leaves a checked-out connection open, so "
        "the release after it still unlocks on that session, then ends it (CR-S3L2-06).",
        f"A lock that cannot be asked within {ENVIRONMENT_LOCK_TIMEOUT_S:g} s "
        "(`ENVIRONMENT_LOCK_TIMEOUT_S`, for the pool's connection and again for the statement), "
        "Postgres unreachable, is no other holder: the start returns `starting` and asks again, "
        "the whole composition with it, after the sweep's backoff "
        f"({SWEEP_RETRY_S[0]:g} s, doubling to {SWEEP_RETRY_S[1]:g} s), each failure logged "
        "(`oms_environment_lock_unanswered`), so `placeOrder` answers `503 oms_not_ready` "
        "meanwhile, as a sweep that meets a store failure does (CR-S3L2-01/02).",
        f"(`tcp_keepalives_idle` {KEEPALIVE['idle']} s, `tcp_keepalives_interval` "
        f"{KEEPALIVE['interval']} s, `tcp_keepalives_count` {KEEPALIVE['count']}, "
        f"`tcp_user_timeout` {STALE_HOLDER_S} s)",
        f"and with it the lock, within about {STALE_HOLDER_S} s: that is the stale-holder window",
        f"the lane ticks every {LANE_TICK_S:g} s (`LANE_TICK_S`) and, on the same tick, asks "
        f"within {ENVIRONMENT_LOCK_TIMEOUT_S:g} s whether the lock's session still holds the key",
        "every new submit is refused `503 oms_not_ready` from then on, while cancels, stop "
        "attaches and repairs, KILLs and the exit routes run on (C-2.6, C-2.21): never a silent "
        "run without the lock, never a blocked exit.",
        f"A lane that has not ticked for {LANE_STALE_S:g} s (`LANE_STALE_S`) is wedged, alive but "
        "stuck: the runtime reads `degraded`, as for a dead lane, and pages the first read of "
        "each stall (CR-S3L1A-02).",
        "and `degraded` whenever its order lane has died or stalled, or the environment's lock is "
        "lost (below)",
        "On the real backend, while the runtime runs, `/readyz` carries an `oms` check",
        "A testnet process's runtime is `degraded` from its start, before any sink is built: "
        "testnet serves connectivity smoke tests only (CONSTITUTION §1.2), and the exchange "
        "adapter builds no testnet trading port, so the runtime fails closed and its `/readyz` "
        "check stays `degraded`.",
    )
    assert "that follow-up is not scheduled" not in _RUNTIME
    assert "loses it without noticing until its stop" not in _RUNTIME
    assert "no request can send any more" in _words(_SCHEMA_DOC)  # the sentence 20 quotes
    guard = _SCHEMA_DOC.split("CREATE FUNCTION rs_guard()", 1)[1].split("END $BODY$;", 1)[0]
    assert "('pending','void')" in guard and "('void'," not in guard  # a `void` row never leaves


def test_21_and_23_note_the_label_the_sweeps_cap_and_the_order_feed() -> None:
    """CR-S3N-02, -04, -08, -09c: 21 owns `actor_label` and the sweep's cap, whose figures are the
    code's (15 s at 200 k rows/s is 3 M rows); 23 says the facade runs on CV-C13's lane, its feed
    hopping to the serving loop, and that an `order` machine's feed removes no entry."""
    row = next(line for line in _SCHEMA_DOC.splitlines() if line.startswith("| `actor_label`"))
    assert _words(row).endswith("survives user deletion; OMS, key import: `user:<role>` |")
    assert (
        "so a row keeps the name it was written with (`auth.login` the typed identifier, an "
        "invite the username, `user:<role>` for OMS and key-import records, whose user is "
        "identified by `actor_user_id`)." in _words(_SCHEMA_DOC)
    )
    rows, rate = 3_000_000, 200_000  # the code's own sizing, beside the cap in `oms_wiring`
    assert rows / rate * 1000 == SWEEP_STATEMENT_TIMEOUT_MS
    section = _SCHEMA_DOC.split("**Deliberately absent indexes:**", 1)[1].split("\n\n", 1)[0]
    assert (
        f"The startup sweep reads it under its own {SWEEP_STATEMENT_TIMEOUT_MS // 1000} s "
        "statement cap (`SWEEP_STATEMENT_TIMEOUT_MS`), sized for about "
        f"{rows // 1_000_000} M orders of the environment's accounts at about {rate // 1000} k "
        "rows/s, figures assumed and unmeasured; past that every attempt times out and is "
        "retried for good, with a WARNING each time and no page, so `/readyz`'s `oms` check "
        "stays `starting` and the OMS never gets ready (fail closed), which is when the read "
        "needs an index." in _words(section)
    )
    attached = ("session", "replay", "alert", "book", "order")  # the five 23 says are fed
    others = [kind for kind in MACHINE_KINDS if kind not in attached]
    assert len(others) == 8
    listing = ", ".join(f"`{kind}`" for kind in others[:-1]) + f" and `{others[-1]}`"
    assert not _missing(
        _words(_WS_DOC),
        "the order facade (E29-T04) runs on 29 CV-C13's dedicated order lane, its own thread "
        "and event loop (`20-architecture.md` §6.2), so `OrderStateFeed` gets each publish on "
        "the serving loop through `call_soon_threadsafe`, never awaited, as a machine on any "
        "other event loop must.",
        "and the OMS runtime attaches the `order` kind (B1, E29-T04 slice 3, `OrderStateFeed`, "
        "bound per order with its account, on the real backend).",
        "A stopped machine removes its entry, except an `order` machine's: `OrderStateFeed` "
        "removes none, so one stopped before its last step leaves its entry as last published; "
        "a terminal one stays 60 s.",
        f"The other eight kinds ({listing}) have no runtime machine yet:",
    )
    assert callable(OmsRuntime.run) and not hasattr(OrderStateFeed, "remove")  # none to call


def test_24_gives_the_demand_and_the_audit_labels_the_code_holds() -> None:
    """CR-S3N-04, -05, -07: 9.3's demand as `ReferenceDemand` takes it, its figures the code's
    constants, and 15.5's label rule as `OmsAudit` writes it, `system:oms` the code's own."""
    sizing = _between(_INTERNAL_DOC, "### 9.3 Sizing algorithm", "**9.3.1 Stop resolution.**")
    ttl, window = int(REFERENCE_DEMAND_TTL_S), int(REFERENCE_DEMAND_WINDOW_S)
    assert (ttl, window) == (REFERENCE_DEMAND_TTL_S, REFERENCE_DEMAND_WINDOW_S)  # whole seconds
    assert not _missing(
        sizing,
        "The stream holds a symbol only while something asks for it, so the binding takes a "
        "demand for a market order's symbol on an ask that had no price: across the runtime, "
        f"at most {REFERENCE_DEMAND_MAX} symbols, at most {REFERENCE_DEMAND_NEW} new ones in "
        f"each {window} s window, each released at the next ask {ttl} s after its last, and all "
        f"at the runtime's stop (`{ReferenceDemand.__name__}`).",
        "A first ask on a symbol nobody watched is therefore a `503`, and a retry after "
        "`Retry-After` finds the price once the stream has the first ticker, unless the "
        "window's budget is spent.",
    )
    assert not _missing(
        _words(_INTERNAL_DOC),
        f"Every record `{OmsAudit.__name__}` writes (E29-T04), whatever its action: "
        f"`actor_label` is `{SYSTEM_ACTOR}`, or `user:<role>` for a request's, as "
        "`accounts/key_import.py` labels its records, and the acting user is `actor_user_id` "
        "with `session_id` and `actor_ip`; a record that names a user but no role is refused, "
        "never written.",
        "The account an order action concerns goes in `after_state` as `account_id`, because "
        "`audit_log` has no account column (21 §3.10.1), so one account's order actions are "
        "read by scanning `after_state`.",
    )


def test_20_runs_the_oms_on_its_own_lane_and_23_and_24_name_what_crosses_it() -> None:
    """#913 slice 3 L1 (29 CV-C13): rule 1's one explicit thread; the lane, its crossings and its
    stop inside the grace, from the code's own bounds; the hops named until L3, L2's and L4's gone;
    the notices' bound and their count (CR-S3L1A-01); the private stream the lane's port refuses
    (CR-S3L1B-05); no blocking hop left (SEC-S3L1A-03), the gate read in place since L4, with its
    read inventory and its two reads; the lane's own refusals read in place (SEC-S3L1C-02); its
    death paged (SEC-S3L1A-02); a cancelled start and nothing begun once the lane stops or dies,
    with OM-D10 to OM-D12 (CR-S3L1C-03); and, the runtime on the lane since L1b, no status note
    left in 20, 23 or 24."""
    rule = _between(_ARCH, "\n1. **One serving loop, and the order lane.**", "\n2. ")
    assert "the one explicit thread is the order lane's" in rule
    lane = _between(_ARCH, "**The order lane (29 CV-C13; #913 slice 3 L1).**", "**Live trading")
    assert not _missing(
        lane,
        "one daemon thread with its own event loop, which never runs a platform-lane task",
        f"failing closed when its loop does not run within {LANE_START_S:g} s",
        "the OMS's own Postgres pool, whose connections belong to the loop that made them",
        "so `ready` is set and cleared on that loop alone",
        "and the calls one thread makes begin in the order it made them:",
        f"awaited and cut at `CV_COMMAND_TIMEOUT` ({HOP_TIMEOUT_S:g} s): the profile cache and the "
        "clock guard's resync; and until L3 lets the lane sign and send from its own loop, every "
        "venue call",
        "the lane's port refuses `subscribe_private` (`PrivateStreamRefused`)",
        "the exit routes reach the exit service the same way (`OnLaneExits`)",
        "cancel-all reaches its own service the same way (`OnLaneCancelAll`): its scope, an "
        "account read, within that bound, and its run within the service's own deadline;",
        "and its refusal records, per-order cancels and amends within the service's own bounds",
        "and the exit routes' in-flight guard, claimed and released on the serving loop only",
        "a rejected credential, which the lane's gate refuses at once until its notice has landed "
        "there (for good, should it be lost or fail)",
        "These notices have no cap of their own: while the serving loop stalls they queue there at "
        "the lane's step rate, so a stall holds at most that rate times its length.",
        "is logged by its call's name and counted (`oms_lane_notices_failed_total`, §12.1)",
        "The switches' gate reads the lane's own refusals of rejected credentials "
        "(`ServedStandings.refused`) on either loop: one dict read, GIL-atomic against the item "
        "the lane assigns and the one the serving loop drops once its notice lands.",
        "Since L4 the lane reads the order-entry gate itself in place too "
        f"(`{ServedGate.__name__}`), never by a hop, its own refusals first",
        "which `observe` and `credential_rejected` publish anew on the serving loop, never "
        "changing one in place, and which a read never writes, a rejection a later pass has "
        "cleared dropped by the next tracking read",
        "the self-check's results, a key at a time, each one `dict.get`",
        "so a read that overlaps one of its writes admits only where the state before or after it "
        "does",
        "Each read takes its source at one instant, so a write is in force for every gate read "
        "that begins after it returns",
        "`_land` writes the key standing before it drops the lane's own refusal, so a read that "
        "misses the one finds the other",
        "so the lane reads the gate twice and admits only when both reads do: a refusing write "
        "that lands inside the first is in force for the second",
        f"within {LANE_JOIN_S:g} s (`LANE_JOIN_S`), the last of the 5 s the drain leaves",
        f"A cancelled `start()` waits, within those {OMS_STOP_RESERVE_S:g} s, for the composition "
        "to close what it built on the lane, then stops the lane, cancelled again meanwhile or not",
        "Once the lane's stop or death has begun, nothing more begins there, and every call is "
        "answered.",
        "A lane whose loop ends without `stop()` has died, logged: the runtime is `degraded` and "
        "pages it once, the first time it reads that state",
    )
    threat = OPENAPI_SPEC_PATH.parents[1] / "security" / "threat-models" / "E29-oms.md"
    rows = {r[2:8]: _words(r) for r in threat.read_text(encoding="utf-8").splitlines()}
    assert not _missing(
        rows["OM-D10"],
        "every venue call M2 signs (F7, `ServedPort`) still runs on the serving loop, awaited",
        "Since L2 the lane records through its own `AuditWriter` and `machine_events` WAL sink, on "
        "its own loop, one hash chain with the serving loop's under `pg_advisory_xact_lock`",
    )
    assert (
        "as a persistence bundle's `machine_events` appends did until #913's L2 gave the lane its "
        "own sink" in rows["OM-D11"]
    )
    assert not [row for row in (rows["OM-D10"], rows["OM-D11"]) if "until L2" in row]
    assert not _missing(
        rows["OM-D12"],
        "`OrderLane.dead` refuses every call (`LaneStopped`, a 503 `oms_not_ready`, nothing "
        "admitted), one racing its death or stop too, unbegun",
        "the runtime pages `oms_lane_died` once per death, on its first read of the lane's state",
    )
    assert "awaits the pipeline on the order lane" in _ROUTE
    ws = _words((OPENAPI_SPEC_PATH.parent / "23-ws-protocol.md").read_text(encoding="utf-8"))
    assert (
        "The lane writes its audit records and `machine_events` rows through its own writer and "
        "sink (#913's L2), so neither waits on the serving loop" in ws
    )
    assert "the order-entry gate it reads in place, never waiting there (#913's L4)" in ws
    assert not _missing(
        _ROUTE,
        "The route's step 10 reads the binding on the serving loop and B1's `SEND` on the order "
        "lane, both in place: the lane never waits on the serving loop for the gate",
        "before the key standing holds it (`20-architecture.md` §6.2, #913 L4)",
    )
    assert not [text for text in (lane, ws, _words(_ARCH)) if "until L2" in text]
    assert not [text for text in (lane, ws, _ROUTE) if "until L4" in text]
    assert "lane to serving loop, blocking" not in lane and "Serving.block" not in _ARCH
    assert not [text for text in (lane, _ROUTE, ws) if "L1b" in text]
    plan = (OPENAPI_SPEC_PATH.parent / "29-statechart-adoption-plan.md").read_text(encoding="utf-8")
    [row] = [line for line in plan.splitlines() if line.startswith("| CV-C13 ")]
    assert "STANDS" in row and "F lane table, `OrderLane`, nightly bench" in row


def test_20_reads_the_order_facades_versions_in_place_beside_the_in_flight_guard() -> None:
    """#913 slice 4 (S4-D2b) on the lane, the orchestrator's Q8 ruling: a `202`'s `ETag` reads B1's
    facade's `version()` from the serving loop, never through the lane, so 20 names it among the
    reads in place, beside the exit routes' in-flight guard."""
    lane = _between(_ARCH, "**The order lane (29 CV-C13; #913 slice 3 L1).**", "**Live trading")
    [read] = [part for part in lane.split(" - ") if part.startswith("read in place:")]
    assert not _missing(
        read,
        "the order facade's `version()`, which a `202`'s `ETag` names (`OrderRoute.versions`, 24 "
        "§8.4), a single read of its order's view, which each committed step replaces whole;",
        "and the exit routes' in-flight guard, claimed and released on the serving loop only",
    )


def test_20_gives_the_lane_its_own_writer_and_sink_on_their_own_wal_files() -> None:
    """#913 slice 3 L2 (rulings Q12, Q13; D6): the lane's own writer and sink, their WAL files, the
    typed refusal of a call from another loop and the stop's bound, from the code's own names; the
    one chain the chain lock keeps."""
    own = _between(
        _ARCH, "**The lane's own audit writer and sink (#913 slice 3 L2;", "**Live trading"
    )
    assert not _missing(
        own,
        "Nothing the OMS records crosses to the serving loop",
        f"The writer's is `{LANE_WAL_PREFIX}<name>` beside `CV_AUDIT_WAL_PATH`, locked",
        f"the sink's is `{LANE_WAL_PREFIX}<name>` beside `CV_MACHINE_EVENT_WAL_PATH`, under the "
        "sink's own lock, a persistence bundle composed or not, so a bundle that comes or goes "
        "across a restart never moves it (SEC-S3L2-03)",
        "Without a bundle no sink of the process holds `CV_MACHINE_EVENT_WAL_PATH` itself: a start "
        "that finds frames there that Postgres has not taken",
        f"refuses, failing closed (`{UnclaimedMachineEvents.__name__}`, logged CRITICAL as "
        "`oms_machine_event_wal_unclaimed` with their size, and paged), before the lane's sink or "
        "the facade exists; it never adopts or skips them",
        f"(`{AuditWriterWrongLoop.__name__}`, an `{AuditUnavailable.__name__}`, so the audited "
        f"action is refused; `{MachineEventWrongLoop.__name__}`), the first refusal of each "
        f"{APPEND_FAILURE_COOLDOWN_S:g} s window, on its clock, logged CRITICAL as a page "
        "(CR-S3L2-08)",
        "The writer's fail-closed alarm, a refused append (its WAL full or unwritable) or its "
        "flusher's death, pages through the runtime's pager (`cv_page`), the first of each "
        f"{LANE_AUDIT_PAGE_S:g} s window per cause (`LANE_AUDIT_PAGE_S`), so an "
        "`audit_unavailable` refusal is never a silent outage (ruling 4)",
        "each insert takes the chain lock (`pg_advisory_xact_lock`) as the serving writer's does",
        f"within its {LANE_AUDIT_STOP_S:g} s (`LANE_AUDIT_STOP_S`) stays in its WAL",
    )
    assert issubclass(AuditWriterWrongLoop, AuditUnavailable)
    assert "always to the order lane's own WAL sink" in _RUNTIME
    lane = _between(_ARCH, "**The order lane (29 CV-C13; #913 slice 3 L1).**", "**Live trading")
    assert (
        "The composition's own unwind, a failed or a cancelled one, shares "
        f"{OMS_STOP_RESERVE_S - LANE_JOIN_S:g} s (`OMS_STOP_RESERVE_S` less `LANE_JOIN_S`) among "
        "its closers, so they fit that wait (SEC-S3L1CG-01)." in lane
    )
    volume = (OPENAPI_SPEC_PATH.parents[1] / "ops" / "runbooks" / "auth-rbac.md").read_text(
        encoding="utf-8"
    )
    held = _between(volume, "**The audit volume (#2615).**", "- **Backup.**")
    assert not _missing(  # CR-S3L2-07: every WAL the volume holds, the lane's own named
        held,
        "the OMS order lane's own audit WAL (`oms_lane.audit.wal`, its cursor and its `.lock`)",
        "the machine-event WAL (`machine_events.wal`, its cursor and its `.lock`)",
        "(`oms_lane.machine_events.wal`, the same three;",
    )


def test_20_24_and_the_e29_model_state_the_gate_in_place_and_its_stall_fence() -> None:
    """#913 slice 3 L4's fold (CR-S3L4-04, CR-S3L4-08; the orchestrator's rulings of 2026-10-25
    18:27Z (2), 19:19Z and 21:56Z): 20 Sec.6.2 and 24 Sec.8.4 state the stall fence on new submits
    and risk-increasing amends with its numbers, from the code's own constants, and its outer
    bounds; the E29 model's OM-D11, F-20 and Sec.11's order-lane row carry L4's gate halves on
    L2's wording, logged as revision 21; and 20 says the stall fence and the lost lock's compose,
    either refusing alone."""
    tick, stale = oms_wiring.SERVING_TICK_S, oms_wiring.SERVING_STALE_S
    assert stale == 2 * tick  # "twice that": the docs' 1 s is two ticks of 0.5 s
    lane = _between(_ARCH, "**The order lane (29 CV-C13; #913 slice 3 L1).**", "**Live trading")
    assert not _missing(
        lane,
        f"where before L4 a gate read it had not begun within {BLOCK_TIMEOUT_S:g} s was "
        "`oms_not_ready`",
        f"So the OMS ticks on the serving loop every {tick:g} s (`SERVING_TICK_S`), a stamp the "
        f"lane reads in place, and once the last tick is over {stale:g} s old, twice that "
        "(`SERVING_STALE_S`), new submits and risk-increasing amends are refused `oms_not_ready` "
        "(`FencedSwitches`: the route's step 10, the pipeline's switches, a re-send, and the exit "
        "service's gate read for a risk-increasing amend, which meets the gate as a submit does: "
        "SR-E28-27, C-2.21), until the serving loop ticks again, never as time passes.",
        "The fence never holds a protective amend, a cancel, cancel-all, a stop attach or a KILL, "
        "none of which reads a switch (C-2.6).",
        f"The account's health decaying to `down` (at most {ACCOUNT_DOWN_MAX_S:g} s after its last "
        f"WS or REST success) and the last tracking read ageing out ({TRACKING_FAULT_AFTER_S:g} "
        "s), each judged at read time, stay the outer bounds.",
        "`FencedSwitches` wraps the binding whose first refusal is the environment lock's fence "
        "(above), so the two compose: either refuses on its own, the stall fence read first.",
    )
    assert "which no longer holds a gate read" not in lane
    assert "the only bounds of a risk-increasing amend's gate read" not in lane
    assert (
        "A new submit's reads of it, the route's, the pipeline's and a re-send's, and a "
        "risk-increasing amend's in the exit service, are fenced: `oms_not_ready` while the "
        f"serving loop has not ticked within {stale:g} s, twice its {tick:g} s tick, and no other "
        "exit reads it (`20-architecture.md` §6.2, #913 L4)."
    ) in _words(_INTERNAL_DOC)
    assert "the exit service's never (`20-architecture.md` §6.2" not in _words(_INTERNAL_DOC)
    threat = OPENAPI_SPEC_PATH.parents[1] / "security" / "threat-models" / "E29-oms.md"
    lines = threat.read_text(encoding="utf-8").splitlines()
    [d11] = [_words(line) for line in lines if line.startswith("| OM-D11 |")]
    [f20] = [_words(line) for line in lines if line.startswith("| F-20 |")]
    [row] = [_words(line) for line in lines if line.startswith("| E29-T04, the order lane (slice")]
    [log] = [_words(line) for line in lines if "| Revision 21, #913 slice 3's L4" in line]
    assert not _missing(
        d11,
        "Since L4 the order-entry gate's reads take no hop (`ServedGate` reads it in place)",
        f"the lane refuses new submits and risk-increasing amends once its {tick:g} s tick is over "
        f"{stale:g} s old (2 \u00d7 {tick:g} s), until it ticks again",  # the times sign (RUF001)
        "L4 reads the gate in place, twice, and on a stall fences new submits and risk-increasing "
        "amends, never a protective exit or KILL",
    )
    assert "A read not begun within 1 s answers `oms_not_ready`" not in d11
    assert "never an exit or a KILL" not in d11
    assert "a stalled serving loop fencing new submits within 1 s instead" in f20
    assert "block the lane until L4" not in f20 and "| With #913's L1d |" in f20
    assert not _missing(
        row,
        "and L4's order-entry gate read in place, twice, with no hop, and its fence on new submits "
        "while the serving loop stalls, shipped with their tests",
        "L2 closed OM-D11's sink half and L4 its gate half",
    )
    assert "CR-S3L4-04" in log and "19:19Z" in log and "21:56Z" in log
    assert "new submits and risk-increasing amends" in log and "never an exit" not in log


def test_24_and_the_route_name_the_stall_fences_step_10_answer_counted_never_audited() -> None:
    """SEC-S3L4-01 (the Fable lens at 8b626ef6): the stall fence's `oms_not_ready` at step 10 is
    the route's third unaudited answer, beside the `501` and step 3's, as it decides nothing on
    the order; it is counted, and a submit the same fence refuses at the pipeline's own read of
    the switches is recorded there. 24 Sec.8.4's sentence and the route's `not_ready()` name it."""
    route = _between(_INTERNAL_DOC, "**The route (E29-T04 slice 3;", "**The exit routes")
    assert not _missing(
        route,
        "Each refusal from step 2 on, the `501` and the `oms_not_ready` of steps 3 and 10 aside, "
        "is audited before it is answered (C-2.9)",
        "Step 10's, the stall fence's (`TradingSwitches`, below), is counted and not audited too, "
        "as it decides nothing on the order; a submit the same fence refuses at the pipeline's "
        "own read of the switches is recorded there (`orders.submit`, `denied`, `oms_not_ready`, "
        "step `switches`).",
    )
    assert "the `501` and step 3's `oms_not_ready` aside" not in route
    tree = ast.parse(inspect.getsource(make_orders_router))
    [not_ready] = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "not_ready"
    ]
    assert not _missing(
        _words(ast.get_docstring(not_ready) or ""),
        "Step 3's answer, and step 10's when the serving loop's stall fence refuses the switches "
        "(24 Sec.8.4 `TradingSwitches`): counted, never audited (24 Sec.8.4)",
    )
