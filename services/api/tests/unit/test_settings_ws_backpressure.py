"""E17-T03 (#412, S1): the backpressure flag and the outbound budget settings.

`CV_WS_BACKPRESSURE_ENABLED` (C-4.13: off by default, removal ticket #2900) and the three
`CV_WS_*` budget settings of `23-ws-protocol.md` §4.3. The queue budget may be lowered, never
raised (D10: the contract value is the ceiling; a raise needs a security review), and the classify
interval is bounded to 500..10 000 ms. Every check is a field check, so a refusal never carries
another setting (#2728, C-12.6).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings
from candleviewer.ws.lifecycle import LIMITS_BLOCK
from candleviewer.ws.limits import MAX_SUBSCRIPTIONS
from candleviewer.ws.outbound import QUEUE_BYTES, QUEUE_FRAMES
from candleviewer.ws.pacing import CLASSIFY_INTERVAL_S

#: The lowest accepted budget: one maximum outbound frame, so a legitimate frame always fits.
FLOOR_BYTES = 4_194_304
#: The lowest accepted frame budget: one snapshot per allowed subscription, plus control replies.
FLOOR_FRAMES = 256
#: An inert marker standing in for a secret value; never a credential.
_MARKER = "cv-412-marker-not-a-secret"
_ENV = (
    "CV_WS_BACKPRESSURE_ENABLED",
    "CV_WS_QUEUE_BYTES",
    "CV_WS_QUEUE_FRAMES",
    "CV_WS_CLASSIFY_INTERVAL_MS",
)
#: The contract ceiling and the floor of each queue budget setting, by field.
_CEILING = {"ws_queue_bytes": QUEUE_BYTES, "ws_queue_frames": QUEUE_FRAMES}
_FLOOR = {"ws_queue_bytes": FLOOR_BYTES, "ws_queue_frames": FLOOR_FRAMES}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def _env(field: str) -> str:
    return f"CV_{field.upper()}"


def _refusal(monkeypatch: pytest.MonkeyPatch, env: str, value: str) -> ValidationError:
    monkeypatch.setenv(env, value)
    with pytest.raises(ValidationError) as refused:
        Settings()
    return refused.value


def test_backpressure_flag_defaults_off() -> None:
    assert Settings().ws_backpressure_enabled is False


@pytest.mark.parametrize(("raw", "expected"), [("true", True), ("false", False)])
def test_backpressure_flag_reads_cv_ws_backpressure_enabled(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool
) -> None:
    monkeypatch.setenv("CV_WS_BACKPRESSURE_ENABLED", raw)

    assert Settings().ws_backpressure_enabled is expected


def test_budget_settings_default_to_the_contract_values() -> None:
    settings = Settings()

    assert settings.ws_queue_bytes == QUEUE_BYTES == 8_388_608
    assert settings.ws_queue_frames == QUEUE_FRAMES == 2_000
    assert settings.ws_classify_interval_ms == round(CLASSIFY_INTERVAL_S * 1000) == 2_000


@pytest.mark.parametrize("field", _CEILING)
def test_queue_budget_settings_cannot_exceed_the_contract(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """D10: one past the contract value is refused, and the refusal names the ceiling."""
    refused = _refusal(monkeypatch, _env(field), str(_CEILING[field] + 1))

    (error,) = refused.errors()
    assert (error["loc"], error["type"], error["ctx"]) == (
        (field,),
        "less_than_equal",
        {"le": _CEILING[field]},
    )


@pytest.mark.parametrize("field", _CEILING)
def test_queue_budget_settings_accept_the_contract_value_and_any_lower_one_to_the_floor(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    ceiling, floor = _CEILING[field], _FLOOR[field]
    for value in (ceiling, (ceiling + floor) // 2, floor):
        monkeypatch.setenv(_env(field), str(value))

        assert getattr(Settings(), field) == value


@pytest.mark.parametrize("field", _CEILING)
def test_queue_budget_settings_are_refused_below_the_floor(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """A budget under the floor closes every connection at its first large frame, so a typo
    (`CV_WS_QUEUE_BYTES=800`) is refused at startup instead."""
    for value in (_FLOOR[field] - 1, 0):
        refused = _refusal(monkeypatch, _env(field), str(value))

        (error,) = refused.errors()
        assert (error["loc"], error["type"], error["ctx"]) == (
            (field,),
            "greater_than_equal",
            {"ge": _FLOOR[field]},
        )


def _declared_bounds(field: str) -> tuple[object, object]:
    """The `ge` and `le` a `Settings` field declares (what the refusals above enforce)."""
    declared = {
        name: getattr(constraint, name)
        for constraint in Settings.model_fields[field].metadata
        for name in ("ge", "le")
        if hasattr(constraint, name)
    }
    return declared["ge"], declared["le"]


def test_the_declared_bounds_come_from_the_contract() -> None:
    """The ceilings are `ws.outbound`'s budget, the byte floor is one maximum outbound frame
    (`welcome.limits`) and the frame floor holds one snapshot per allowed subscription. M1 may
    not import `ws`, so `settings.py` spells the numbers out and this keeps them from drifting."""
    assert _declared_bounds("ws_queue_bytes") == (
        LIMITS_BLOCK["max_outbound_frame_bytes"],
        QUEUE_BYTES,
    )
    assert _declared_bounds("ws_queue_bytes")[0] == FLOOR_BYTES
    assert _declared_bounds("ws_queue_frames") == (FLOOR_FRAMES, QUEUE_FRAMES)
    assert FLOOR_FRAMES > MAX_SUBSCRIPTIONS
    assert _declared_bounds("ws_classify_interval_ms") == (500, 10_000)


@pytest.mark.parametrize(
    ("value", "accepted"),
    [(499, False), (500, True), (2_000, True), (10_000, True), (10_001, False), (0, False)],
)
def test_classify_interval_bounds(
    monkeypatch: pytest.MonkeyPatch, value: int, accepted: bool
) -> None:
    """D10: 500..10 000 ms; the 2 s default (§8.3) is inside."""
    if accepted:
        monkeypatch.setenv("CV_WS_CLASSIFY_INTERVAL_MS", str(value))

        assert Settings().ws_classify_interval_ms == value
    else:
        refused = _refusal(monkeypatch, "CV_WS_CLASSIFY_INTERVAL_MS", str(value))

        (error,) = refused.errors()
        assert error["loc"] == ("ws_classify_interval_ms",)


@pytest.mark.parametrize(
    ("env", "value"),
    [
        ("CV_WS_BACKPRESSURE_ENABLED", "maybe"),
        ("CV_WS_QUEUE_BYTES", str(QUEUE_BYTES + 1)),
        ("CV_WS_QUEUE_BYTES", "not-a-number"),
        ("CV_WS_QUEUE_FRAMES", str(QUEUE_FRAMES + 1)),
        ("CV_WS_CLASSIFY_INTERVAL_MS", "1"),
    ],
    ids=["flag", "bytes_over", "bytes_not_int", "frames_over", "interval_under"],
)
@pytest.mark.parametrize(
    "secret",
    ["CV_BYBIT_API_KEY", "CV_BYBIT_API_SECRET", "CV_AUTH_PEPPER", "CV_PG_DSN"],
)
def test_a_refused_ws_backpressure_setting_never_echoes_another_setting(
    monkeypatch: pytest.MonkeyPatch, env: str, value: str, secret: str
) -> None:
    """#2728: `hide_input_in_errors` hides input from `str()` only, and a model validator's
    `errors()` and `json()` carry every setting. These checks are field checks (C-12.6)."""
    monkeypatch.setenv(secret, _MARKER)

    error = _refusal(monkeypatch, env, value)

    assert len(error.errors()) == 1
    assert _MARKER not in str(error)
    assert _MARKER not in repr(error.errors())
    assert _MARKER not in error.json()
