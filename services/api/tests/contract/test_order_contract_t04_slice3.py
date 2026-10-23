"""Contract (#913, E29-T04 slice 3): the texts that sub-slices B to G code against, read from 22,
21 (10.7, 13.1), 20 (6.2, 7.2, 12.1), 24 (8.4) and the regenerated models, never from a copy:
the orchestrator's slice-3 rulings of 2026-10-23 (Q2 to Q12, Q16, Q18, Q20), with the code lens's
findings on them folded (CR-S3A-01 to CR-S3A-15)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from candleviewer.accounts.verification import Refusal
from candleviewer.api._generated import openapi_models as rest
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.exchange.bybit.key_info import refusal
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.oms import submit
from candleviewer.oms_wiring import OmsBounds
from candleviewer.settings import (
    OMS_AFTER_ANCHOR_S,
    OMS_STOP_RESERVE_S,
    TEARDOWN_BUDGET_S,
    Settings,
)
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT, CV_PERSIST_TIMEOUT
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.openapi_helpers import deref

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_RESPONSES: dict[str, Any] = _SPEC["components"]["responses"]
_PLACE: Any = _SPEC["paths"]["/orders"]["post"]
_ARCH, _SCHEMA_DOC, _INTERNAL_DOC = (
    (OPENAPI_SPEC_PATH.parent / name).read_text(encoding="utf-8")
    for name in ("20-architecture.md", "21-database-schema.md", "24-internal-schemas.md")
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
    assert "(on `placeOrder` the `trading.oms_enabled` flag, then live trading not" in general
    order = general.split("**Order of the checks on an order submit or amend (E29-T04).**")[1]
    item = _between(_INTERNAL_DOC, "\n1. After authentication, CSRF", "\n2. ")
    for text in (order, item):  # 22's order and 24's step 1 agree
        at = [text.index(s) for s in ("lookup", "`trading.oms_enabled` flag", "live trading")]
        assert at == sorted(at)
        assert "the `trading.oms_enabled` flag (`placeOrder` only)" in text
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
    assert not _missing(
        _RUNTIME,
        "Status: this text, down to the startup self-check, is the contract of #913 slice 3 "
        "(sub-slices B to G); nothing serves it until they land.",
        "The lifespan starts the runtime after the account health runtime, then E29-T05's",
        "`placeOrder` answers `503 oms_not_ready` with `Retry-After`",
        "must fit a deploy's 60 s `/readyz` smoke window",
        "`/readyz` carries an `oms` check that gives the runtime's state and nothing else: `ok` "
        "once `ready`; until then it fails, its detail `starting` while the sweep runs, or "
        "`degraded` once the runtime will not get ready",
        "`/readyz` is anonymous, so the check names no posture",
        "That stop is the lifespan's, run before `Supervisor.stop_all`, not the supervised OMS "
        "module's, but it keeps within that module's 15 s grace",
        "in a demo or testnet process whatever `CV_TRADING_LIVE_ENABLED` says, and in a live "
        "process only while that setting is off",
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
        "(24 §8.4); 1000-8000, so 2 ",
        "+ the submit timeout ≤ 10 s, the stop request's bound (`oms_wiring.STOP_REQUEST_BOUND_S`",
    )
    top = OmsBounds.from_settings(Settings(oms_submit_timeout_ms=8000, oms_inflight_stuck_s=120))
    assert 2 * CV_PERSIST_TIMEOUT + top.submit_timeout_s == top.stop_request_s == 10
    assert top.submit_timeout_s < CV_COMMAND_TIMEOUT
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


def test_the_etag_waits_for_slice_4_an_algo_for_its_epics_and_held_rows_are_scanned() -> None:
    """Q11, Q12 and Q16: no index for `held` now, and 21 says the read scans for it."""
    assert "required" not in _SPEC["components"]["headers"]["ETag"]  # an optional header
    text = _words(_PLACE["responses"]["202"]["description"])
    assert "is sent once `amendOrder` defines and checks it (#913 slice 4, ruling Q11)" in text
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
