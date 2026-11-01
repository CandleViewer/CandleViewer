"""Rule control, notification and journal handlers (24 §11.5; E35-T13 slice 4b).

`pause_rule` and `enable_rule` move another rule (or, for `pause_rule`, the rule itself) through
the rules manager's system path (`RuleControl`), from the dispatch worker under `CONTROL_TIMEOUT_S`,
never on the tick: a target the move does not reach is recorded `skipped`, its `blocked_detail`
saying why. `enable_rule` never names its own rule, checked here at execution as the validator
checks it at save (E35-FR-17). `send_notification` writes one `rule.notify` outbox row keyed by the
action's fire key (`NotificationOutbox`, bound at the composition root) and awaits no delivery;
`log_journal_tag` answers its tag, which the executor writes as a `rule_events` `log` row with the
action's `action_ok` row. None of them names an account, sends an order or touches a stop (C-2.6).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from string import Template
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol
from uuid import UUID

from candleviewer.rules.executor.handlers import Capability, HandlerAnswer, Prepared, prepared
from candleviewer.rules.executor.keys import dedupe_key, request_sha256
from candleviewer.rules.ir.canonical import dec_str
from candleviewer.rules.scope import ActionRequest

#: The outbox topic of a rule's notification (`21-database-schema.md` §3.10.4).
RULE_NOTIFY_TOPIC: Final = "rule.notify"
#: The bound on a control action's B9 move and on a notification's outbox write.
CONTROL_TIMEOUT_S: Final = 2.0
NOTIFY_TIMEOUT_S: Final = 2.0
ControlMove = Literal["pause_rule", "enable_rule"]
#: Why a rule-control action's target did not take its move (24 §11.5).
ControlSkip = Literal[
    "control_not_found", "control_protected", "control_self", "control_unreadable",
    "control_state",
]  # fmt: skip
#: PROPOSED for the owner, as `results.BLOCKED_DETAIL` is (E35-D03 §6's register): one sentence
#: each, naming the condition and never data. A missing, a deleted and another owner's rule share
#: one sentence, so no answer tells them apart.
CONTROL_DETAIL: Final[Mapping[ControlSkip, str]] = MappingProxyType(
    {
        "control_not_found": "Not done — the target is not one of this owner's rules.",
        "control_protected": "Not done — a protected system rule is never changed by a rule.",
        "control_self": "Not done — a rule never enables itself.",
        "control_unreadable": "Not done — the target rule's active version cannot be read.",
        "control_state": "Not done — the target rule's state does not take this change.",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ControlRequest:
    """One rule-control action's move: the target as the action names it, and the acting rule's
    identity its record carries (the actor `rule:<rule_id>@v<n>`, both users' ids)."""

    move: ControlMove
    target: str
    owner: UUID
    rule_id: str
    version: int
    run_id: UUID
    node_id: str
    armed_by: str | None


class RuleControl(Protocol):
    """The rules manager's system path (`RulesManager.control_rule`): the move made (`None`) or
    why the target did not take it."""

    async def control_rule(self, request: ControlRequest) -> ControlSkip | None: ...


class RuleControlHandler:
    """`pause_rule` (B9 `DISARM`) or `enable_rule` (B9 `SAVE`, toward `simulate`): `ok` once the
    target moved, `skipped` with its detail when it did not, `unknown` when the move did not end
    within `CONTROL_TIMEOUT_S`, `failed` (`invalid_params`) without a `rule_id`."""

    capability: Capability = "rule_control"

    def __init__(self, move: ControlMove, control: RuleControl) -> None:
        self._move, self._control = move, control

    def prepare(
        self, req: ActionRequest, account_id: UUID | None, *, max_notional_usd: Decimal | None
    ) -> Prepared:
        target = req.payload.params.get("rule_id")
        if not isinstance(target, str) or not target:
            return prepared({"invalid": True})
        request = ControlRequest(
            move=self._move, target=target, owner=req.owner, rule_id=req.rule_id,
            version=req.version, run_id=req.run_id, node_id=req.payload.node_id,
            armed_by=req.armed_by,
        )  # fmt: skip
        return Prepared(MappingProxyType({"control": request}), _fingerprint(request))

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        request = prepared.request.get("control")
        if not isinstance(request, ControlRequest):
            return HandlerAnswer("refused", error_code="invalid_params")
        if request.move == "enable_rule" and request.target == request.rule_id:
            return _skipped("control_self")  # E35-FR-17, at execution as at save
        try:
            async with asyncio.timeout(CONTROL_TIMEOUT_S):
                skip = await self._control.control_rule(request)
        except TimeoutError:
            return HandlerAnswer("no_answer", error_code="timeout")
        return HandlerAnswer("done") if skip is None else _skipped(skip)


def _skipped(skip: ControlSkip) -> HandlerAnswer:
    return HandlerAnswer("skipped", detail=CONTROL_DETAIL[skip])


def _fingerprint(request: ControlRequest) -> str:
    return request_sha256({"move": request.move, "target": request.target})


@dataclass(frozen=True, slots=True, kw_only=True)
class NotifyRow:
    """One `rule.notify` outbox row: its key the action's fire key, its payload ids, the channel,
    the severity and the rendered text, never a figure the rule saw."""

    dedupe_key: str
    payload: Mapping[str, Any] = field(repr=False)


class NotificationOutbox(Protocol):
    """The outbox writer, bound at the composition root: the row, landed once per key."""

    async def enqueue(self, row: NotifyRow) -> None: ...


def render(template: str, values: Mapping[str, Any]) -> str:
    """`template` with each `$name` or `${name}` of `values` put in place, as text, a `$$` written
    as one `$` and every other `$` kept as written (`string.Template.safe_substitute`): nothing is
    evaluated, and no attribute or index is ever read."""
    return Template(template).safe_substitute({k: _text(v) for k, v in values.items()})


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, int | Decimal):
        return dec_str(Decimal(value))
    if isinstance(value, float):
        return dec_str(Decimal(float.__repr__(value)))
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


class NotificationHandler:
    """`send_notification` (24 §11.5): one `rule.notify` row through the outbox, `ok` once written
    under `NOTIFY_TIMEOUT_S`, never awaiting a delivery; a repeat of the action's fire key lands
    once (`ux_outbox_dedup`). `failed` (`invalid_params`) unless `channel`, `severity` and
    `template` are strings and `vars` a mapping or absent; `unknown` when the write did not end in
    time."""

    capability: Capability = "notifications"

    def __init__(self, outbox: NotificationOutbox) -> None:
        self._outbox = outbox

    def prepare(
        self, req: ActionRequest, account_id: UUID | None, *, max_notional_usd: Decimal | None
    ) -> Prepared:
        params = req.payload.params
        channel, severity, template = (params.get(k) for k in ("channel", "severity", "template"))
        values = params.get("vars")
        texts = (channel, severity, template)
        if not all(isinstance(t, str) and t for t in texts) or not isinstance(
            values, Mapping | None
        ):
            return prepared({"invalid": True})
        key = dedupe_key(
            rule_id=req.rule_id,
            version=req.version,
            scope_instance=req.instance.key,
            node_id=req.payload.node_id,
            run_id=req.run_id,
            account_id=account_id,
        )  # the action's own fire key, as the executor derives it (24 §11.9)
        return prepared({
            "dedupe_key": key, "rule_id": req.rule_id, "version": req.version,
            "run_id": str(req.run_id), "node_id": req.payload.node_id, "channel": channel,
            "severity": severity, "text": render(str(template), values or {}),
        })  # fmt: skip

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        request = prepared.request
        if request.get("invalid"):
            return HandlerAnswer("refused", error_code="invalid_params")
        payload = {k: v for k, v in request.items() if k != "dedupe_key"}
        row = NotifyRow(dedupe_key=str(request["dedupe_key"]), payload=payload)
        try:
            async with asyncio.timeout(NOTIFY_TIMEOUT_S):
                await self._outbox.enqueue(row)
        except TimeoutError:
            return HandlerAnswer("no_answer", error_code="timeout")
        return HandlerAnswer("done")


class JournalTagHandler:
    """`log_journal_tag` (24 §11.5): its tag and note answered, which the executor writes as a
    `rule_events` `log` row with the action's `action_ok` row, for E41 to read from the run log;
    `failed` (`invalid_params`) unless `tag` is a string and `note` a string or absent."""

    capability: Capability = "journal"

    def prepare(
        self, req: ActionRequest, account_id: UUID | None, *, max_notional_usd: Decimal | None
    ) -> Prepared:
        tag, note = req.payload.params.get("tag"), req.payload.params.get("note")
        if not isinstance(tag, str) or not tag or not isinstance(note, str | None):
            return prepared({"invalid": True})
        return prepared({"tag": tag, "note": note})

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        if prepared.request.get("invalid"):
            return HandlerAnswer("refused", error_code="invalid_params")
        tag, note = prepared.request["tag"], prepared.request["note"]
        return HandlerAnswer("done", journal={"tag": tag, "note": note})
