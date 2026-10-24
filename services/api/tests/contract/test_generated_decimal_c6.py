"""C6 on the generated models (#906 slice G, finding R1S-01 on #4083): a `Decimal` member that
the contract makes nullable is a string that fully matches the contract's `Decimal` pattern and
nothing else. No exponent, no padding, no JSON number, no `bool`, no digit tuple; and a refusal
is a validation error, so a 422 at the edge, never a `decimal.InvalidOperation`, so a 500."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.error_redaction import install_error_redaction

#: Real generated models with a nullable `Decimal`: (model, the members its body needs besides the
#: one under test, that member). The first two are #4083's profile write body, the third a response.
_HOLDERS: dict[str, tuple[type[BaseModel], dict[str, object], str]] = {
    "risk_caps": (api.ProfileRiskCaps, {}, "max_position_notional_usd"),
    "sizing": (api.ProfileSizing, {"mode": "fixed_qty"}, "qty"),
    "tp_sl_result": (api.TpSlResult, {}, "take_profit"),
}
_EACH_HOLDER = pytest.mark.parametrize("holder", _HOLDERS)
_REFUSED: dict[str, object] = {
    "garbage": "abc",
    "empty": "",
    "huge_exponent": "1E+9999999",
    "exponent": "1e3",
    "padded": "  7 ",
    "trailing_newline": "7\n",
    "underscore": "7_000",
    "plus_sign": "+5",
    "no_whole_digits": ".5",
    "no_fraction_digits": "5.",
    "bare_minus": "-",
    "arabic_indic_digit": "\u0663",
    "nan": "NaN",
    "infinity": "Infinity",
    "bool": True,
    "int": 1,
    "float": 1.5,
    "digit_tuple": [0, [1], 5],
    "object": {"a": 1},
}


def _build(holder: str, value: object) -> BaseModel:
    model, base, member = _HOLDERS[holder]
    return model.model_validate({**base, member: value})


def _accepts(model: type[BaseModel], payload: dict[str, object]) -> bool:
    """Whether `model` takes `payload`; any error but a `ValidationError` is the test's failure."""
    try:
        model.model_validate(payload)
    except ValidationError:
        return False
    return True


@_EACH_HOLDER
@pytest.mark.parametrize("bad", list(_REFUSED.values()), ids=list(_REFUSED))
def test_nullable_decimal_refuses_what_is_not_a_c6_string_as_a_validation_error(
    holder: str, bad: object
) -> None:
    with pytest.raises(ValidationError) as refused:
        _build(holder, bad)
    assert [error["loc"][0] for error in refused.value.errors()] == [_HOLDERS[holder][2]]


@_EACH_HOLDER
@pytest.mark.parametrize(
    "raw", ["1e3", "1E400", "0.1", "12", "true", '"1e3"', '" 7 "', '"1E+9999999"', "[0,[1],5]"]
)
def test_nullable_decimal_refuses_raw_json_that_is_not_a_c6_string(holder: str, raw: str) -> None:
    """`model_validate_json`, as a route that parses its own body calls it."""
    model, base, member = _HOLDERS[holder]
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps({**base, member: "@"}).replace('"@"', raw))


@_EACH_HOLDER
@pytest.mark.parametrize(
    "text",
    ["12.5", "-0.001", "0", "-0", "63120.50", "0.100000000000000000001", "1000000000000000000000"],
)
def test_nullable_decimal_round_trips_a_c6_string_as_a_json_string(holder: str, text: str) -> None:
    member, built = _HOLDERS[holder][2], _build(holder, text)
    assert getattr(built, member) == Decimal(text)
    assert built.model_dump(mode="json")[member] == text
    assert json.loads(built.model_dump_json())[member] == text  # a JSON string, never a number


@_EACH_HOLDER
def test_nullable_decimal_takes_a_finite_decimal_instance(holder: str) -> None:
    built = _build(holder, Decimal("12.5"))
    assert built.model_dump(mode="json")[_HOLDERS[holder][2]] == "12.5"


@_EACH_HOLDER
@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_nullable_decimal_refuses_a_non_finite_decimal_instance(holder: str, bad: str) -> None:
    with pytest.raises(ValidationError):
        _build(holder, Decimal(bad))


@_EACH_HOLDER
def test_nullable_decimal_stays_nullable_and_omittable(holder: str) -> None:
    model, base, member = _HOLDERS[holder]
    assert getattr(_build(holder, None), member) is None
    assert getattr(model.model_validate(base), member) is None


def test_decimal_list_members_check_every_item() -> None:
    assert api.Bid.model_validate(["63120.50", "1.5"]).root == [Decimal("63120.50"), Decimal("1.5")]
    assert not _accepts(api.HeatmapResponse, {"prices": ["1", "1e3"]})
    with pytest.raises(ValidationError) as refused:
        api.Bid.model_validate(["63120.50", "1E+9999999"])
    assert refused.value.errors()[0]["loc"] == (1,)


@settings(max_examples=300, deadline=None)
@given(text=st.text(alphabet="0123456789-+.eE _\n\t\u0663\uff11", max_size=12))
def test_nullable_decimal_takes_exactly_the_strings_a_plain_c6_member_takes(text: str) -> None:
    """`ProfileTakeProfit.value` is the contract's `Decimal` collapsed to a pattern-checked `str`,
    so pydantic-core's regex engine decides it; the alias, run by Python's, must agree on every
    string and must never raise anything but a `ValidationError`."""
    plain = _accepts(api.ProfileTakeProfit, {"unit": "ticks", "value": text})
    assert _accepts(api.ProfileRiskCaps, {"max_position_notional_usd": text}) == plain


def _app() -> FastAPI:
    app = FastAPI()
    install_error_redaction(app)

    @app.post("/caps")
    async def post_caps(body: api.ProfileRiskCaps) -> dict[str, Any]:
        return body.model_dump(mode="json")

    return app


async def _post(payload: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.post("/caps", json=payload)


@pytest.mark.parametrize(
    "bad",
    ["abc", "1E+9999999", "9" * 100_000 + "x", 1.5, True, ["a b c"], {"k": "a b c"}],
    ids=["abc", "exp", "long", "num", "bool", "list", "object"],
)
async def test_post_with_a_bad_decimal_answers_the_project_422_with_a_bounded_body(
    bad: object,
) -> None:
    response = await _post({"max_position_notional_usd": bad})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["code"] == "validation_failed"
    assert [error["field"] for error in problem["errors"]] == ["body.max_position_notional_usd"]
    assert len(response.content) < 4096
    assert re.search(r"(.)\1{9999}", response.text) is None
    # The message is the validator's constant one: it never echoes what the client sent.
    assert str(bad)[:20] not in response.text


@pytest.mark.parametrize("sent", ["12.5", None])
async def test_post_with_a_c6_decimal_or_null_is_accepted(sent: str | None) -> None:
    response = await _post({"max_position_notional_usd": sent})
    assert response.status_code == 200
    assert response.json()["max_position_notional_usd"] == sent
