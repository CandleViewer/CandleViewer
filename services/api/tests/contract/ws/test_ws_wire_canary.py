"""E17-T07 (#572): the load-bearing facts of `cv.v1`, written out a second time.

`packages/protocol/wire-contract.v1.golden.json` pins the whole wire, and a tool rewrites it. These
literals are the same facts in a test that nothing regenerates. They are applied to the contract the
implementation speaks (`wire_contract.collect()`), not to the golden file, and judged by the tool's
own rules, so a change that removes or alters one fails here until this file is edited in the same
PR: re-baselining the golden is then also a visible edit of a test, and a breaking change cannot
pass by regenerating one file. A change the README calls additive does not fail it: a new body
kind, close code, close reason or subprotocol, a new limits key, a floor raised, a ceiling lowered,
a request bound widened, a promise about what the server sends narrowed. The closed facts are
exact: the header, the 19 frame types and a revoked session."""

from __future__ import annotations

import copy
import functools
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[5]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.contracts import wire_contract as wc  # noqa: E402

Contract = dict[str, Any]
Mutation = Callable[[Contract], None]

#: The header, 23 section 3.4: closed, so compared exactly.
_HEADER = {
    "bytes": 24,
    "endianness": "little",
    "magic": "0x43565742",
    "flags": ["estimated", "coalesced", "replay", "partial"],
}
#: body_kind id -> (name, format_version, record stride in bytes). A kind above 6 may be added.
_BODY_KINDS = {
    "1": ("book_snapshot", 1, 17),
    "2": ("book_delta", 1, 17),
    "3": ("trades", 1, 22),
    "4": ("bars", 2, 85),
    "5": ("footprint", 2, 33),
    "6": ("heatmap_column", 1, 16),
}
#: The envelope's `t` values, 23 section 3.1: closed, so compared exactly.
_FRAME_TYPES = (
    "hello",
    "welcome",
    "auth",
    "auth_ok",
    "sub",
    "sub_ok",
    "unsub",
    "unsub_ok",
    "snap",
    "d",
    "resync",
    "revoked",
    "permission_change",
    "ping",
    "pong",
    "err",
    "ctl",
    "ctl_ok",
    "bye",
)
#: The close codes the gateway sends and the host adds, and the one reason whose pair is frozen: a
#: code may be added, and none may go. A revoked session is exact: 4401, and not reconnected.
_CLOSE_CODES = {
    "gateway": [1000, 1001, 1002, 1009, 1011, 1013, 4400, 4401, 4403, 4429],
    "host_only": [1012],
    "reasons": {"session_revoked": {"code": 4401, "reconnect": False}},
}
_SUBPROTOCOLS = {"offered": ["cv.v1.msgpack", "cv.v1.json"], "protocol": "cv.v1"}
#: `welcome.limits` at the shipped defaults, 23 section 4.2: the bound kind is exact, a floor may
#: rise and a ceiling may fall, and a seventh key may be added.
_LIMITS = {
    "max_subscriptions": {"floor": 200},
    "max_topics_per_request": {"floor": 50},
    "max_inbound_frame_bytes": {"floor": 262_144},
    "max_outbound_frame_bytes": {"ceiling": 4_194_304},
    "min_throttle_ms": {"ceiling": 50},
    "max_symbols_per_connection": {"floor": 40},
}
_ITEM = {"type": "string", "minLength": 1, "maxLength": 64}
#: The bounds the first commit of the branch set: a request bound may widen and may not narrow, a
#: promise about what the server sends may narrow and may not widen.
_BOUNDS = {
    "common.subId": {"side": "response", "type": "string", "minLength": 1, "maxLength": 64},
    "ctl.metrics": {
        "side": "request",
        "type": "array",
        "minItems": 1,
        "maxItems": 12,
        "items": _ITEM,
    },
    "sub.indicator_options.from_seq": {"side": "request", "type": "integer", "minimum": 0},
    "sub.options.from_seq": {"side": "request", "type": "integer", "minimum": 0},
    "sub.options.metrics": {
        "side": "request",
        "type": "array",
        "minItems": 1,
        "maxItems": 12,
        "items": _ITEM,
    },
    "sub.options.rule_ids": {
        "side": "request",
        "type": "array",
        "maxItems": 100,
        "items": {"type": "string"},
    },
    "sub.options.status": {"side": "request", "type": "array", "maxItems": 16, "items": _ITEM},
    "sub.options.symbols": {
        "side": "request",
        "type": "array",
        "minItems": 1,
        "maxItems": 40,
        "items": {"type": "string"},
    },
    "sub_ok.results.sub_id": {
        "side": "response",
        "type": "string",
        "minLength": 1,
        "maxLength": 64,
    },
}


@functools.cache
def _contract() -> Contract:
    return wc.collect().contract


def _golden_of_the_facts(contract: Contract) -> Contract:
    """`contract` with the facts written out here in place of what it says: the golden this file
    stands for, in the golden's own shape, so the tool's rules judge it."""
    golden = copy.deepcopy(contract)
    golden["header"] = {**contract["header"], **copy.deepcopy(_HEADER)}
    golden["body_kinds"] = {
        kind: {
            **contract["body_kinds"].get(kind, {"length_rule": "min", "record": []}),
            "name": name,
            "format_version": version,
            "record_stride": stride,
        }
        for kind, (name, version, stride) in _BODY_KINDS.items()
    }
    golden["envelope"] = {**contract["envelope"], "frame_types": list(_FRAME_TYPES)}
    golden["close_codes"] = copy.deepcopy(_CLOSE_CODES)
    golden["subprotocols"] = copy.deepcopy(_SUBPROTOCOLS)
    golden["limits"] = copy.deepcopy(_LIMITS)
    golden["bounds"] = copy.deepcopy(_BOUNDS)
    return golden


def _broken(contract: Contract, prefix: str = "") -> list[str]:
    """The paths under `prefix` where `contract` breaks a fact written out here."""
    findings = wc.compare(_golden_of_the_facts(contract), contract)
    return [f.path for f in wc.breaking(findings) if f.path.startswith(prefix)]


def test_the_header_is_24_bytes_little_endian_with_the_cvwb_magic_and_four_flags() -> None:
    assert _broken(_contract(), "header") == []


def test_the_six_body_kinds_keep_their_names_versions_and_record_strides() -> None:
    assert _broken(_contract(), "body_kinds") == []


def test_the_envelope_has_exactly_these_19_frame_types() -> None:
    assert len(_FRAME_TYPES) == 19
    assert _broken(_contract(), "envelope.frame_types") == []


def test_the_gateway_closes_with_these_ten_codes_and_the_host_adds_1012() -> None:
    assert _broken(_contract(), "close_codes") == []


def test_a_revoked_session_closes_4401_and_is_not_reconnected() -> None:
    reasons = _contract()["close_codes"]["reasons"]
    assert reasons["session_revoked"] == {"code": 4401, "reconnect": False}


def test_welcome_advertises_the_six_limits_as_these_floors_and_ceilings() -> None:
    assert _broken(_contract(), "limits") == []


def test_the_bounds_the_first_commit_set_hold() -> None:
    assert _broken(_contract(), "bounds") == []


def test_the_protocol_is_cv_v1_and_both_codecs_are_offered() -> None:
    assert _broken(_contract(), "subprotocols") == []


def _set(path: str, value: Any) -> Mutation:
    def apply(c: Contract) -> None:
        *parents, last = path.split("|")
        node: Any = c
        for key in parents:
            node = node[key]
        node[last] = value

    return apply


def _append(path: str, value: Any) -> Mutation:
    def apply(c: Contract) -> None:
        node: Any = c
        for key in path.split("|"):
            node = node[key]
        node.append(value)

    return apply


def _remove(path: str, value: Any) -> Mutation:
    def apply(c: Contract) -> None:
        node: Any = c
        for key in path.split("|"):
            node = node[key]
        node.remove(value)

    return apply


def _delete(path: str) -> Mutation:
    def apply(c: Contract) -> None:
        *parents, last = path.split("|")
        node: Any = c
        for key in parents:
            node = node[key]
        del node[last]

    return apply


_KIND_7 = {"name": "x", "format_version": 1, "length_rule": "min", "record_stride": 8, "record": []}
#: What the README calls additive: the canary lets each pass.
ADDITIVE: list[Any] = [
    pytest.param(_set("body_kinds|7", _KIND_7), id="body-kind-7"),
    pytest.param(_append("close_codes|gateway", 4430), id="close-code-added"),
    pytest.param(
        _set("close_codes|reasons|queue_full", {"code": 4429, "reconnect": True}),
        id="close-reason-added",
    ),
    pytest.param(_append("subprotocols|offered", "cv.v1.cbor"), id="subprotocol-added"),
    pytest.param(_set("limits|max_subscriptions", {"floor": 300}), id="floor-raised"),
    pytest.param(_set("limits|min_throttle_ms", {"ceiling": 20}), id="ceiling-lowered"),
    pytest.param(_set("limits|max_things", {"seen": 5}), id="limits-key-added"),
    pytest.param(_set("bounds|sub.options.metrics|maxItems", 16), id="request-bound-widened"),
    pytest.param(_set("bounds|common.subId|maxLength", 32), id="response-bound-narrowed"),
    pytest.param(
        _set("bounds|ctl.reason", {"side": "request", "type": "string", "maxLength": 64}),
        id="pinned-bound-added",
    ),
]
#: What breaks `cv.v1`: the canary fails on each.
BREAKING: list[Any] = [
    pytest.param(_set("header|bytes", 32), id="header-size-changed"),
    pytest.param(_set("header|magic", "0x43565743"), id="header-magic-changed"),
    pytest.param(_append("header|flags", "compressed"), id="header-flag-named"),
    pytest.param(_set("body_kinds|3|record_stride", 24), id="body-kind-stride-changed"),
    pytest.param(_set("body_kinds|4|format_version", 3), id="body-kind-version-changed"),
    pytest.param(_delete("body_kinds|4"), id="body-kind-removed"),
    pytest.param(_append("envelope|frame_types", "cancel"), id="frame-type-added"),
    pytest.param(_remove("envelope|frame_types", "ctl"), id="frame-type-removed"),
    pytest.param(_remove("close_codes|gateway", 4429), id="close-code-removed"),
    pytest.param(_remove("close_codes|host_only", 1012), id="host-close-code-removed"),
    pytest.param(
        _set("close_codes|reasons|session_revoked|reconnect", True), id="revoked-session-reconnects"
    ),
    pytest.param(
        _set("close_codes|reasons|session_revoked|code", 4403), id="revoked-session-moved"
    ),
    pytest.param(_remove("subprotocols|offered", "cv.v1.json"), id="subprotocol-removed"),
    pytest.param(_set("subprotocols|protocol", "cv.v2"), id="protocol-renamed"),
    pytest.param(_set("limits|max_subscriptions", {"floor": 100}), id="floor-lowered"),
    pytest.param(_set("limits|min_throttle_ms", {"ceiling": 100}), id="ceiling-raised"),
    pytest.param(
        _set("limits|max_subscriptions", {"ceiling": 200}), id="limits-bound-kind-changed"
    ),
    pytest.param(_delete("limits|max_symbols_per_connection"), id="limits-key-removed"),
    pytest.param(_set("bounds|sub.options.from_seq|minimum", 1), id="request-bound-narrowed"),
    pytest.param(_set("bounds|common.subId|maxLength", 4096), id="response-bound-widened"),
    pytest.param(_delete("bounds|sub.options.status"), id="pinned-bound-removed"),
]


@pytest.mark.parametrize("mutate", ADDITIVE)
def test_a_change_the_readme_calls_additive_does_not_fail_the_canary(mutate: Mutation) -> None:
    contract = copy.deepcopy(_contract())
    mutate(contract)
    assert _broken(contract) == []


@pytest.mark.parametrize("mutate", BREAKING)
def test_a_change_that_breaks_cv_v1_fails_the_canary(mutate: Mutation) -> None:
    contract = copy.deepcopy(_contract())
    mutate(contract)
    assert _broken(contract), "the canary should have failed"
