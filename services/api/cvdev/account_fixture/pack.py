"""E27 accounts fault-injection pack: the test-side loader (E27-Q01, #833).

The pack lives in `packages/fixtures/accounts/` (its README is the user guide). This module turns
one scenario into concrete data, the same way for every test:

- REST: `Scenario.reply(method, path, at_ms=...)` follows the manifest's lookup rule (the
  scenario's own answers along its `extends` chain, then the overlays named with it, then the
  root `compliant`; in each, the exact call before `*`; a call nothing answers raises
  `UnstubbedCall`), loads the payload, applies the clock and then the RFC 7396 merge patch.
- Clock (test plan section 9.5): every exchange-side time is anchored on an injected, tz-aware
  `now`: the envelope `time`, server time, rate-limit reset headers and the key's created and
  expiry times, with `deadlineDay` derived from the expiry. No wall clock is read, so tests can
  freeze time. It is not an application clock: a running stack's test clock is #2893's.
- Account (test plan section 9.2): key info reports the UID the key is attached to, and
  `isMaster`/`parentUid` from that account's kind; `Scenario.egress_ip` is what the IP echo
  check answers.
- Private WS: `Scenario.ws` is the script as data (reactions, frames after auth, timeline).
- Runtime switch: `load(..., switched=True)` answers as the scenario's `switch_to` target while
  keeping its own key id and account (test plan section 9.3; the switch on a stack is #2893's).

It serves nothing and opens no socket. A transport that serves a scenario to a running stack
(`CV_ACCOUNT_FIXTURE=<scenario>`) is #2893; tests drive the adapter's own client through an
`httpx.MockTransport` built on `Scenario.reply`.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Final

PACK_ROOT: Final = Path(__file__).resolve().parents[4] / "packages" / "fixtures" / "accounts"
SCHEMA_PATH: Final = PACK_ROOT / "manifest.schema.json"
#: Payloads come from the fixtures package only: the pack and the shared corpus beside it.
_PAYLOAD_ROOT: Final = PACK_ROOT.parent.resolve()
#: Test plan section 9.2: the accounts a key is stored on, by UID, each with the main account it
#: belongs to (`None` for a main account).
ACCOUNT_PARENTS: Final[Mapping[str, str | None]] = {
    "90000001": None,  # acct-demo-main
    "90000011": "90000001",  # acct-demo-sub1
    "90000012": "90000001",  # acct-demo-sub2
}
#: The deployment egress every scenario's IP echo check answers (RFC 5737; README).
EGRESS_IP: Final = "203.0.113.10"
WILDCARD: Final = "*"
#: The `origin` that marks an overlay (test plan section 9.3).
OVERLAY: Final = "overlay"
_DAY: Final = timedelta(days=1)
_KEY_INFO_CALL: Final = "GET /v5/user/query-api"
_SERVER_TIME_CALL: Final = "GET /v5/market/time"
_WS_FIELDS: Final = ("on_connect", "on_auth", "on_subscribe", "on_ping", "after_auth", "timeline")
_CLOCK_FIELDS: Final = ("server_offset_ms", "key_created_offset_ms", "key_expires_offset_ms")


class UnstubbedCall(LookupError):
    """A call the scenario does not answer: a test failure, never a silent success."""


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    body: Any
    headers: Mapping[str, str]
    #: The reply's exchange code and message could not be confirmed (README).
    code_unconfirmed: bool


@dataclass(frozen=True, slots=True)
class WsReaction:
    do: str  # "reply" | "ignore" | "close"
    frame: Any | None


@dataclass(frozen=True, slots=True)
class WsSend:
    after_ms: int
    frame: Any
    every_ms: int | None
    label: str | None


@dataclass(frozen=True, slots=True)
class WsStep:
    at_ms: int
    do: str  # "drop" | "refuse_reconnects" | "accept_reconnects" | "silence"
    label: str | None


@dataclass(frozen=True, slots=True)
class PrivateWs:
    on_connect: str  # "accept" | "refuse"
    on_auth: WsReaction
    on_subscribe: WsReaction
    on_ping: WsReaction
    after_auth: tuple[WsSend, ...]
    timeline: tuple[WsStep, ...]


@dataclass(frozen=True, slots=True)
class Clock:
    now: datetime
    server_offset_ms: int
    key_created_offset_ms: int
    key_expires_offset_ms: int | None

    @property
    def now_ms(self) -> int:
        return int(self.now.timestamp() * 1000)

    @property
    def server_ms(self) -> int:
        """The stub exchange's clock, epoch milliseconds."""
        return self.now_ms + self.server_offset_ms

    @property
    def key_created_at(self) -> datetime:
        return self.now + timedelta(milliseconds=self.key_created_offset_ms)

    @property
    def key_expires_at(self) -> datetime | None:
        if self.key_expires_offset_ms is None:
            return None
        return self.now + timedelta(milliseconds=self.key_expires_offset_ms)


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7396 JSON merge patch; returns a new value and mutates neither input."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out: dict[str, Any] = copy.deepcopy(target) if isinstance(target, dict) else {}
    for name, value in patch.items():
        if value is None:
            out.pop(name, None)
        else:
            out[name] = merge_patch(out.get(name), value)
    return out


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def _payload(ref: str) -> Any:
    """A payload file, relative to the pack root; callers get a deep copy. A path that leaves the
    fixtures package is refused even if the schema's path pattern were loosened."""
    path = (PACK_ROOT / ref).resolve()
    if not path.is_relative_to(_PAYLOAD_ROOT):
        raise ValueError(f"payload {ref} is outside the fixtures package")
    return _read(path)


def schema() -> dict[str, Any]:
    body: dict[str, Any] = _read(SCHEMA_PATH)
    return body


def scenario_names() -> list[str]:
    return sorted(p.parent.name for p in PACK_ROOT.glob("*/manifest.json"))


def manifest(name: str) -> dict[str, Any]:
    path = PACK_ROOT / name / "manifest.json"
    if not path.is_file():
        raise KeyError(f"no such scenario: {name}")
    body: dict[str, Any] = _read(path)
    return body


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _frame(entry: Mapping[str, Any]) -> Any:
    body = copy.deepcopy(_payload(str(entry["payload"])))
    if "merge_patch" in entry:
        body = merge_patch(body, entry["merge_patch"])
    return body


def _reaction(entry: Mapping[str, Any]) -> WsReaction:
    return WsReaction(str(entry["do"]), _frame(entry) if "payload" in entry else None)


def _active(stub: Mapping[str, Any], at_ms: int) -> bool:
    return int(stub.get("from_ms", 0)) <= at_ms < int(stub.get("until_ms", 2**63))


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    #: The named manifest: its key id, account and expected outcome.
    own: Mapping[str, Any]
    #: The manifests that answer, nearest first: the scenario (or, once switched, its
    #: `switch_to` target) and every scenario it extends, up to the root.
    chain: tuple[Mapping[str, Any], ...]
    clock: Clock
    account_uid: str
    key_id: str
    #: What the IP echo check answers (SR-033).
    egress_ip: str
    ws: PrivateWs
    #: The overlays named with the scenario, in the order named (test plan section 9.3).
    overlays: tuple[Mapping[str, Any], ...] = ()

    @property
    def expected(self) -> Mapping[str, Any]:
        value: Mapping[str, Any] = self.own["expected"]
        return value

    def typed_secret(self) -> str:
        """The secret a tester types for this scenario's key (README rule; never stored)."""
        return f"fixture-{self.name}-secret-not-real"

    def _answering(self) -> tuple[Mapping[str, Any], ...]:
        """The README lookup order: the scenario's own answers (a fault), then the overlays
        (seeded state), then the root's defaults."""
        return (*self.chain[:-1], *self.overlays, self.chain[-1])

    def stubbed_calls(self) -> frozenset[str]:
        return frozenset(call for m in self._answering() for call in m.get("rest", {}))

    def reply(self, method: str, path: str, *, at_ms: int = 0) -> Reply:
        """The reply to `method path` at `at_ms` after the scenario starts."""
        call = f"{method.upper()} {path}"
        for entry in self._answering():
            rest = entry.get("rest", {})
            for key in (call, WILDCARD):
                stub = rest.get(key)
                if stub is not None and _active(stub, at_ms):
                    return self._render(call, stub)
        raise UnstubbedCall(f"{self.name}: nothing answers {call} at {at_ms} ms")

    def _render(self, call: str, stub: Mapping[str, Any]) -> Reply:
        body = copy.deepcopy(_payload(str(stub["payload"])))
        self._anchor(call, body)
        if "merge_patch" in stub:
            body = merge_patch(body, stub["merge_patch"])
        headers = {name: self._header(value) for name, value in stub.get("headers", {}).items()}
        return Reply(
            status=int(stub.get("http_status", 200)),
            body=body,
            headers=headers,
            code_unconfirmed=bool(stub.get("code_unconfirmed", False)),
        )

    def _header(self, value: Any) -> str:
        if isinstance(value, dict):
            return str(self.clock.server_ms + int(value["now_offset_ms"]))
        return str(value)

    def _anchor(self, call: str, body: Any) -> None:
        """Re-time a reply on the injected clock (README, 'Clock'); the merge patch runs after."""
        if not isinstance(body, dict):
            return
        if type(body.get("time")) is int:
            body["time"] = self.clock.server_ms
        result = body.get("result")
        if not isinstance(result, dict):
            return
        if call == _SERVER_TIME_CALL and "timeSecond" in result:
            result["timeSecond"] = str(self.clock.server_ms // 1000)
            result["timeNano"] = str(self.clock.server_ms * 1_000_000)
        if call == _KEY_INFO_CALL and "userID" in result:
            parent = ACCOUNT_PARENTS[self.account_uid]
            result["userID"] = int(self.account_uid)
            result["isMaster"] = parent is None
            result["parentUid"] = "0" if parent is None else parent
            result["createdAt"] = _iso(self.clock.key_created_at)
            expires = self.clock.key_expires_at
            result["expiredAt"] = "" if expires is None else _iso(expires)
            if "deadlineDay" in result:
                if expires is None:  # no documented value without an expiry: leave none
                    del result["deadlineDay"]
                else:  # days left to the expiry, rounded up, as in the source fixture
                    result["deadlineDay"] = max(0, math.ceil((expires - self.clock.now) / _DAY))


@dataclass(frozen=True, slots=True)
class RotationPair:
    name: str
    old: Scenario
    new: Scenario
    expected: Mapping[str, Any]


def _chain(name: str) -> tuple[dict[str, Any], ...]:
    chain: list[dict[str, Any]] = []
    current: str | None = name
    while current is not None:
        if any(m["scenario"] == current for m in chain):
            raise ValueError(f"{name}: extends cycle through {current}")
        entry = manifest(current)
        chain.append(entry)
        current = entry.get("extends")
    return tuple(chain)


def _merged(
    chain: tuple[dict[str, Any], ...], field: str, inner: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for entry in reversed(chain):
        value = entry.get(field, {})
        out.update(value.get(inner, {}) if inner is not None else value)
    return out


def _overlay(name: str) -> dict[str, Any]:
    body = manifest(name)
    if body.get("origin") != OVERLAY:
        raise ValueError(f"{name} is not an overlay")
    return body


def load(
    name: str,
    *,
    now: datetime,
    account_uid: str | None = None,
    overlays: Iterable[str] = (),
    switched: bool = False,
) -> Scenario:
    """Resolve key scenario `name` with every time anchored on `now` (tz-aware).

    `now` is the scenario start, which `Scenario.reply(..., at_ms=...)` and the WS timeline count
    from: when the scenario is loaded or, for one a stored key is switched to at runtime, the
    switch (test plan section 9.3; TC-411's T0). `account_uid` is the account the key is attached
    to (default: the manifest's), one of the section 9.2 accounts in `ACCOUNT_PARENTS`; key info
    reports it unless the scenario's merge patch pins another UID (`uid_mismatch`). `overlays`
    names overlays to combine with it, in order. `switched` answers as the scenario's `switch_to`
    target, after the runtime switch, with this scenario's key id and account
    (`stored_key_rejected`)."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    own = manifest(name)
    if own.get("origin") == OVERLAY:
        raise ValueError(f"{name} is an overlay: name it in overlays")
    if "rotation" in own:
        raise ValueError(f"{name} is a rotation pair: use load_rotation")
    answering = own.get("switch_to") if switched else name
    if answering is None:
        raise ValueError(f"{name} has no runtime switch")
    chain = _chain(str(answering))
    uid = account_uid or str(own["tester_inputs"]["account_uid"])
    if uid not in ACCOUNT_PARENTS:
        raise ValueError(f"{uid} is not a section 9.2 account that holds a key")
    clock = _merged(chain, "clock")
    ws = _merged(chain, "ws", "private")
    egress = next((str(m["egress_ip"]) for m in chain if "egress_ip" in m), None)
    missing = [f for f in _CLOCK_FIELDS if f not in clock] + [f for f in _WS_FIELDS if f not in ws]
    if egress is None:
        missing.append("egress_ip")
    if missing:
        raise ValueError(f"{name}: unresolved {', '.join(missing)}")
    return Scenario(
        name=name,
        own=own,
        chain=chain,
        clock=Clock(
            now=now,
            server_offset_ms=int(clock["server_offset_ms"]),
            key_created_offset_ms=int(clock["key_created_offset_ms"]),
            key_expires_offset_ms=clock["key_expires_offset_ms"],
        ),
        account_uid=uid,
        key_id=str(own["tester_inputs"]["key_id"]),
        egress_ip=str(egress),
        ws=PrivateWs(
            on_connect=str(ws["on_connect"]),
            on_auth=_reaction(ws["on_auth"]),
            on_subscribe=_reaction(ws["on_subscribe"]),
            on_ping=_reaction(ws["on_ping"]),
            after_auth=tuple(
                WsSend(int(s["after_ms"]), _frame(s), s.get("every_ms"), s.get("label"))
                for s in ws["after_auth"]
            ),
            timeline=tuple(
                WsStep(int(s["at_ms"]), str(s["do"]), s.get("label")) for s in ws["timeline"]
            ),
        ),
        overlays=tuple(_overlay(o) for o in overlays),
    )


def load_rotation(name: str, *, now: datetime, overlays: Iterable[str] = ()) -> RotationPair:
    """Resolve a rotation pair; both keys belong to the pair's account and see its overlays."""
    own = manifest(name)
    pair = own.get("rotation")
    if pair is None:
        raise ValueError(f"{name} is not a rotation pair")
    uid = str(own["tester_inputs"]["account_uid"])
    named = tuple(overlays)
    return RotationPair(
        name=name,
        old=load(str(pair["old_key"]), now=now, account_uid=uid, overlays=named),
        new=load(str(pair["new_key"]), now=now, account_uid=uid, overlays=named),
        expected=own["expected"],
    )
