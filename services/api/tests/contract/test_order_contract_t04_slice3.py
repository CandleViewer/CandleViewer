"""Contract (#913, E29-T04 slice 3): the texts that sub-slices B to G code against, read from 22,
21 (3.10.1, 10.7, 12, 13.1), 20 (6.2, 7.2, 12.1), 23 (6.4), 24 (8.4, 9.3, 15.5) and the
regenerated models, never from a copy: the orchestrator's slice-3 rulings of 2026-10-23 (Q2 to
Q12, Q16, Q18, Q20), with the code lens's findings on them folded (CR-S3A-01 to CR-S3A-15, and
CR-S3N-01 to CR-S3N-09 on the notes of 20, 21, 23 and 24)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from candleviewer.accounts.verification import Refusal
from candleviewer.api._generated import openapi_models as rest
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.audit.machine_events import APPEND_FAILURE_COOLDOWN_S, MachineEventWrongLoop
from candleviewer.audit.writer import AuditUnavailable, AuditWriterWrongLoop
from candleviewer.exchange.bybit.key_info import refusal
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.oms import submit
from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms_lane import BLOCK_TIMEOUT_S, HOP_TIMEOUT_S, LANE_JOIN_S, LANE_START_S
from candleviewer.oms_wiring import (
    ENVIRONMENT_LOCK_NAMESPACE,
    ENVIRONMENT_LOCK_TIMEOUT_S,
    LANE_AUDIT_PAGE_S,
    LANE_AUDIT_STOP_S,
    LANE_WAL_PREFIX,
    REFERENCE_DEMAND_MAX,
    REFERENCE_DEMAND_NEW,
    REFERENCE_DEMAND_TTL_S,
    REFERENCE_DEMAND_WINDOW_S,
    SWEEP_RETRY_S,
    SWEEP_STATEMENT_TIMEOUT_MS,
    SYSTEM_ACTOR,
    EnvironmentLocked,
    OmsAudit,
    OmsBounds,
    OmsRuntime,
    OrderStateFeed,
    ReferenceDemand,
    UnclaimedMachineEvents,
    environment_lock_key,
)
from candleviewer.settings import (
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
        "Each refusal from step 2 on, the `501` and step 3's `oms_not_ready` aside, is audited",
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
        "Status of these two: the contract of #913 slice 3 (sub-slices B to G); nothing serves",
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
        "The lock is its session's: a holder whose connection drops (a cut network, a Postgres "
        "restart) loses it without noticing until its stop",
        "On the real backend, while the runtime runs, `/readyz` carries an `oms` check",
        "A testnet process's runtime is `degraded` from its start, before any sink is built: "
        "testnet serves connectivity smoke tests only (CONSTITUTION §1.2), and the exchange "
        "adapter builds no testnet trading port, so the runtime fails closed and its `/readyz` "
        "check stays `degraded`.",
    )
    assert "that follow-up is not scheduled" not in _RUNTIME
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
    stop inside the grace, from the code's own bounds; the hops named until L3 and L4, L2's gone;
    the notices' bound and their count (CR-S3L1A-01); the private stream the lane's port refuses
    (CR-S3L1B-05); the blocking hops' bound in series (SEC-S3L1A-03); the lane's own refusals read
    in place (SEC-S3L1C-02); its death paged (SEC-S3L1A-02); a cancelled start and nothing begun
    once the lane stops or dies, with OM-D10 to OM-D12 (CR-S3L1C-03); and, the runtime on the lane
    since L1b, no status note left in 20, 23 or 24."""
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
        "lane to serving loop, blocking: until L4 the order-entry gate, whose key-standing read is "
        "not safe from another thread. The lane's thread waits",
        "the lane's port refuses `subscribe_private` (`PrivateStreamRefused`)",
        "the exit routes reach the exit service the same way (`OnLaneExits`)",
        "cancel-all reaches its own service the same way (`OnLaneCancelAll`): its scope, an "
        "account read, within that bound, and its run within the service's own deadline;",
        "and its refusal records, per-order cancels and amends within the service's own bounds",
        "and the exit routes' in-flight guard, claimed and released on the serving loop only",
        f"waits at most `CV_PERSIST_TIMEOUT` ({BLOCK_TIMEOUT_S:g} s) for the call to begin",
        "a rejected credential, which the lane's gate refuses at once until its notice has landed "
        "there (for good, should it be lost or fail)",
        "The bound is per call: while the serving loop stalls, N such calls hold the lane's thread "
        "N times that bound in series, ahead of any other step there, the ruled interim until L4",
        "These notices have no cap of their own: while the serving loop stalls they queue there at "
        "the lane's step rate, so a stall holds at most that rate times its length.",
        "is logged by its call's name and counted (`oms_lane_notices_failed_total`, §12.1)",
        "The switches' gate reads the lane's own refusals of rejected credentials "
        "(`ServedStandings.refused`) on either loop: one dict read, GIL-atomic against the item "
        "the lane assigns and the one the serving loop drops once its notice lands.",
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
    assert not _missing(
        rows["OM-D11"],
        "as a persistence bundle's `machine_events` appends did until #913's L2 gave the lane its "
        "own sink",
        f"A read not begun within {BLOCK_TIMEOUT_S:g} s answers `oms_not_ready`, refused, never "
        "open",
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
    assert not [text for text in (lane, ws, _words(_ARCH)) if "until L2" in text]
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
