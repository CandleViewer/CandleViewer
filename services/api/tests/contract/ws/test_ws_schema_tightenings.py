"""E17-T07 (#572): the three tightenings of 23-ws-protocol.md §13 that had to land before `cv.v1`
froze, because a later one would be breaking (C-6.3): `s` on `snap` and `d` (§13.1), the `sub_id`
of a `sub_ok` result (§13.5) and the `welcome.limits` required set (§13.3). The server already
conformed; these pin that the schemas now say so, with a frame each must refuse and one each must
accept."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from candleviewer.ws.lifecycle import welcome_payload
from candleviewer.ws.limits import SUB_ID_MAX_LEN
from tests.contract.ws._harness import SCHEMAS, _validator

_BASE = "cv://ws/v1/"
#: The six `welcome.limits` keys of `cv.v1`, written out. Each must be a property and be required. A
#: seventh key is additive when it is an optional property that is not listed in `required`: the
#: wire-contract golden pins `required`, and adding to it is breaking (packages/protocol/README.md,
#: "Compatibility: additive or breaking?").
_FROZEN_LIMITS = (
    "max_subscriptions",
    "max_topics_per_request",
    "max_inbound_frame_bytes",
    "max_outbound_frame_bytes",
    "min_throttle_ms",
    "max_symbols_per_connection",
)
_DATA = {"ch": "trades.BTCUSDT", "ts": 1_789_132_262_104, "p": {}}


def _errors(schema: str, doc: Any) -> list[str]:
    return [e.message for e in _validator(f"{_BASE}{schema}.schema.json").iter_errors(doc)]


@pytest.mark.parametrize(
    "frame",
    [
        pytest.param({"t": "d", **_DATA}, id="d-without-s"),
        pytest.param({"t": "d", "s": None, **_DATA}, id="d-with-null-s"),
        pytest.param({"t": "d", "s": "1", **_DATA}, id="d-with-a-string-s"),
        pytest.param({"t": "snap", **_DATA}, id="snap-without-s"),
    ],
)
def test_envelope_refuses_a_d_without_an_integer_s_and_a_snap_without_s(
    frame: dict[str, Any],
) -> None:
    assert _errors("envelope", frame)


@pytest.mark.parametrize(
    "frame",
    [
        pytest.param({"t": "d", "s": 1, **_DATA}, id="d"),
        pytest.param({"t": "snap", "s": 1_048_577, **_DATA}, id="complete-snap"),
        pytest.param({"t": "snap", "s": None, "id": "set-1", **_DATA}, id="chunk-not-the-last"),
    ],
)
def test_envelope_accepts_s_where_13_1_allows_it(frame: dict[str, Any]) -> None:
    assert _errors("envelope", frame) == []


@pytest.mark.parametrize(
    "sub_id",
    [
        pytest.param("", id="empty"),
        pytest.param("s" * (SUB_ID_MAX_LEN + 1), id="over-the-bound"),
        pytest.param(5, id="int"),
    ],
)
def test_sub_ok_result_sub_id_is_a_sub_id(sub_id: Any) -> None:
    results = {"results": [{"ch": "trades.BTCUSDT", "ok": True, "sub_id": sub_id}]}
    assert _errors("sub_ok", results)


def test_sub_ok_result_accepts_a_sub_id_up_to_its_bound() -> None:
    for sub_id in ("s_01", "s" * SUB_ID_MAX_LEN):
        results = {"results": [{"ch": "trades.BTCUSDT", "ok": True, "sub_id": sub_id}]}
        assert _errors("sub_ok", results) == []


def _welcome() -> dict[str, Any]:
    return welcome_payload(
        encoding="json",
        server_version="1.0.0",
        git_sha="abc",
        connection_id="ws_1",
        server_time_ms=1,
        client_clock_ms=None,
        features={},
    )


def test_welcome_requires_every_limit_the_server_sends() -> None:
    assert _errors("welcome", _welcome()) == []
    assert set(_FROZEN_LIMITS) <= set(_welcome()["limits"])  # a seventh, optional key is allowed
    for key in _FROZEN_LIMITS:
        payload = _welcome()
        del payload["limits"][key]
        assert [m for m in _errors("welcome", payload) if key in m], key


def _welcome_limits_schema() -> dict[str, Any]:
    limits: dict[str, Any] = SCHEMAS[f"{_BASE}welcome.schema.json"]["properties"]["limits"]
    return copy.deepcopy(limits)


def _limits_schema_problems(limits: dict[str, Any]) -> list[str]:
    """What this file requires of the `welcome.limits` schema: each frozen key is a property and is
    required. A seventh, optional property is not a problem."""
    return [
        f"{key}: {what}"
        for key in _FROZEN_LIMITS
        for what, present in (
            ("not a property", key in limits["properties"]),
            ("not required", key in limits["required"]),
        )
        if not present
    ]


def test_welcome_limits_has_the_six_frozen_keys_present_and_required() -> None:
    limits = _welcome_limits_schema()
    assert _limits_schema_problems(limits) == []
    assert limits["additionalProperties"] is False  # a new key is added here, as an optional one


def test_a_seventh_optional_limits_key_is_not_a_problem() -> None:
    limits = _welcome_limits_schema()
    limits["properties"]["max_things"] = {"type": "integer"}  # a property, not in `required`
    assert _limits_schema_problems(limits) == []


@pytest.mark.parametrize("key", _FROZEN_LIMITS)
def test_a_frozen_limits_key_made_optional_or_dropped_is_a_problem(key: str) -> None:
    limits = _welcome_limits_schema()
    limits["required"].remove(key)
    assert _limits_schema_problems(limits) == [f"{key}: not required"]
    del limits["properties"][key]
    assert _limits_schema_problems(limits) == [f"{key}: not a property", f"{key}: not required"]


# --- #572: the `sub` and `ctl` options say what the registry enforces, set before the freeze ---


def _uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _sub(**opts: Any) -> dict[str, Any]:
    return {"topics": [{"ch": "trades.BTCUSDT", "opts": opts}]}


@pytest.mark.parametrize("value", [None, -1, "1", 1.5, True])
def test_from_seq_is_a_whole_number_never_null(value: Any) -> None:
    assert _errors("sub", _sub(from_seq=value))
    instances = [{"indicator": "sma", "params": {}}]
    assert _errors(
        "sub",
        {
            "topics": [
                {
                    "ch": "indicators.BTCUSDT.time.1",
                    "opts": {"instances": instances, "from_seq": value},
                }
            ]
        },
    )


def test_from_seq_accepts_zero_and_a_sequence_number() -> None:
    for value in (0, 1_048_577):
        assert _errors("sub", _sub(from_seq=value)) == []


@pytest.mark.parametrize(
    "opts",
    [
        pytest.param({"metrics": []}, id="metrics-none"),
        pytest.param({"metrics": ["m"] * 13}, id="metrics-13"),
        pytest.param({"metrics": [""]}, id="metrics-empty-name"),
        pytest.param({"metrics": ["m" * 65]}, id="metrics-long-name"),
        pytest.param({"symbols": []}, id="symbols-none"),
        pytest.param({"status": ["open"] * 17}, id="status-17"),
        pytest.param({"status": [""]}, id="status-empty"),
        pytest.param({"status": ["s" * 65]}, id="status-long"),
        pytest.param({"rule_ids": [_uuid(n) for n in range(101)]}, id="rule-ids-101"),
    ],
)
def test_a_list_option_past_the_registrys_bound_is_refused_by_the_schema(
    opts: dict[str, Any],
) -> None:
    assert _errors("sub", _sub(**opts))


@pytest.mark.parametrize(
    "opts",
    [
        pytest.param({"metrics": ["m" * 64] * 12}, id="metrics-12-of-64"),
        pytest.param({"symbols": ["BTCUSDT"]}, id="symbols-1"),
        pytest.param({"status": ["open"] * 16}, id="status-16"),
        pytest.param({"rule_ids": [_uuid(n) for n in range(100)]}, id="rule-ids-100"),
    ],
)
def test_a_list_option_at_the_registrys_bound_is_accepted_by_the_schema(
    opts: dict[str, Any],
) -> None:
    assert _errors("sub", _sub(**opts)) == []


@pytest.mark.parametrize("metrics", [[], ["m"] * 13, [""], ["m" * 65]])
def test_ctl_metrics_is_bounded_as_sub_metrics_is(metrics: list[str]) -> None:
    assert _errors("ctl", {"metrics": metrics})
    assert _errors("ctl", {"metrics": ["cvd"] * 12}) == []
