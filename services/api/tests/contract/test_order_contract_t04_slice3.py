"""Contract (#913, E29-T04 slice 3): the texts that sub-slices B to G code against, read from 22,
21 (10.7, 13.1), 20 (6.2, 7.2, 12.1), 24 (8.4) and the regenerated models, never from a copy:
the orchestrator's slice-3 rulings of 2026-10-23 (Q2 to Q12, Q16, Q18, Q20)."""

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
from candleviewer.oms import commands, idempotency, ports, submit
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
    """Q2: a required boolean, true while the order is unresolved, a first answer included."""
    schema = _SCHEMAS["OrderAcceptance"]
    member = schema["properties"]["reconciling"]
    assert (schema["required"][-1], member["type"]) == ("reconciling", "boolean")
    text = _words(member["description"])
    assert "or while its state could not be read; a first answer included" in text
    states = set(_SCHEMAS["OrderLifecycleState"]["enum"])
    assert _UNRESOLVED < states and "reconciling" not in states
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
    """Q3, Q18: after the lookup, before the switches; owned, with a removal ticket (C-4.13)."""
    assert not _missing(
        _PLACE_TEXT,
        "while off, refuses a new admission with `403 trading_disabled` and no `reason`",
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
    section = _SCHEMA_DOC.split("### 10.7 Feature flags", 1)[1].split("### 10.8 ", 1)[0]
    [row] = [line for line in section.splitlines() if line.startswith("| `trading.oms_enabled`")]
    cells = "|".join(cell.strip() for cell in row.strip("|").split("|")[1:])
    assert cells == "boolean|`false`|New OMS orders; owner @basiltt, removal #4227|`all_roles`"
    assert "the insert-only `ensure` of a demo process seeds it `true`" in _words(section)
    assert "share a database the first `ensure` decides" in _words(section)


def test_every_not_ready_case_answers_one_503_and_the_fake_backend_a_501() -> None:
    """Q7, Q8: the runtime, the catalogue, an unmeasured clock; `clock_drift` stays measured."""
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
    )


def test_24_gives_the_routes_checks_in_the_ruled_order_and_audits_each_refusal() -> None:
    """The brief's order; Q9: a lost record is `403` up to existence, then 503 (C-2.9)."""
    section = _INTERNAL_DOC.split("**The route (E29-T04 slice 3;", 1)[1].split("\n\nEach ", 1)[0]
    heads = re.findall(r"^\d+\. ([^:,(;]+)", section, re.MULTILINE)
    assert [head.strip() for head in heads] == [
        *("the principal", "RBAC", "the OMS runtime", "the account's existence", "the arm token"),
        *("`Idempotency-Key`", "the 24 h record", "the anchor's lookup"),
        *("the `trading.oms_enabled` flag", "the switches", "the body", "`submit`"),
    ]
    assert not _missing(
        _ROUTE,
        "with `requires_trade`, so a Manager needs a grant that allows trading",
        "with no oracle",
        "`503 oms_not_ready` with `Retry-After`",
        "`algo_unsupported`, until E32 and E34",
        "shielded from the client's disconnect and from the request's deadline",
        "at most `CV_OMS_DRAIN_S`",
        "steps 2 and 4 as `rbac.denied`, the gate's as `account.disabled_by_policy`",
        "every other as `orders.submit` with outcome `denied` and its code",
        "any later refusal whose record cannot be written answers `503 audit_unavailable`",
    )
    assert submit.SUBMIT_ACTION == "orders.submit" and "denied" in _SCHEMAS["AuditOutcome"]["enum"]
    assert "stays `403` when its record cannot be written; any later refusal" in _PLACE_TEXT


def test_live_needs_both_preconditions_and_the_switches_run_live_b18_gate() -> None:
    """Q4, Q5: the setting and the flag; the announced B18 interim; synchronous (C-2.21)."""
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
    )
    switches = _between(_INTERNAL_DOC, "**`TradingSwitches`", "**A refused")
    assert "live trading enabled, then the B18 kill switch, then the order-entry gate" in switches
    row = _between(_ARCH, "| OMS | `oms_interim_ports{port}` |", "\n")
    assert "slice 3 ruling Q5: `kill_switch`, the B18 kill switch until E39-S03" in row


def test_20_starts_the_oms_after_account_health_and_sweeps_before_ready() -> None:
    """Q7, Q20: the sweep's steps in order, per environment, `ready` last; Q6: the sink."""
    section = _ARCH.split("**OMS runtime (E29-T04 slice 3, #913).**", 1)[1].split("\n\nA ", 1)[0]
    steps = re.findall(r"^\d\. (.*)$", section, re.MULTILINE)
    keys = ("`CV_OMS_STARTUP_WAIT_S`", "`void_orphans`", "hydrates", "abandons", "sets `ready`")
    assert [key in step for key, step in zip(keys, steps, strict=True)] == [True] * 5
    assert "for each account of the process environment, never for every account" in steps[1]
    assert not _missing(
        _RUNTIME,
        "The lifespan starts the runtime after the account health runtime, then E29-T05's",
        "`placeOrder` answers `503 oms_not_ready` with `Retry-After`",
        "only while `CV_TRADING_LIVE_ENABLED` is off (demo, testnet)",
        "With it on and no bundle the runtime fails closed",
        "It never uses an in-memory sink",
    )


def test_20_declares_the_oms_settings_within_the_bounds_the_code_holds() -> None:
    """The code's defaults; the ranges keep the stop, command and stuck bounds the code holds."""
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
    assert (commands.SUBMIT_TIMEOUT_S * 1000, idempotency.STUCK_AFTER_S) == (5000, 30)
    assert "1000-8000" in rows["CV_OMS_SUBMIT_TIMEOUT_MS"][3]
    assert 2 * CV_PERSIST_TIMEOUT + 8 <= ports.STOP_REQUEST_BOUND_S and 8 < CV_COMMAND_TIMEOUT
    after = CV_PERSIST_TIMEOUT + submit.PLACE_WAIT_S + submit.RESULT_WAIT_S
    assert after + 4 * submit.STORE_TIMEOUT_S - commands.SUBMIT_TIMEOUT_S == 12
    assert "(submit + 12 s), ≤ 120" in rows["CV_OMS_INFLIGHT_STUCK_S"][3]


def test_a_refused_credential_fails_closed_for_the_process_until_a_recorded_pass() -> None:
    """Q10 and its rider: an unlisted code or none is `unknown_key`; the durable step follows."""
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
        "no later order on the account is admitted in this process until a recorded pass",
        "it pages the Owner",
        "is a named follow-up of #913",
    )
    gate = _between(_INTERNAL_DOC, "**8.4.1 Account checks", "### 8.5 ")
    assert "whose durable reaction is that ticket's named follow-up" in gate


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
