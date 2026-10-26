"""Constant validation messages (C-12.6, #4562): no `422` message the shared handler answers for a
path or query parameter depends on the characters sent. Each value is sent with a twin that has
every letter and digit replaced (same length, same shape); a message that differs between the
two quotes input, and its error type belongs in `CONSTANT_MESSAGES`."""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from pydantic import UUID4, BaseModel, Field

from candleviewer.api import error_redaction
from candleviewer.api.error_redaction import CONSTANT_MESSAGES, install_error_redaction

#: Maps digits and some letters (not those a parser reads: exponent, unit, inf/nan, boolean), so any
#: message that depends on the value differs from its twin's; that is the point.
_TWIN = str.maketrans("GJKQVXZgjkqvz0123456789", "QXZGJKVqvzgjk5678901234")
_VALUES = ("G0kz-JQX-vvjg", "2026-13-45", "9" * 40, "zq-12345678-1234-1234-1234", "1" * 31 + "Kj")


class _Side(enum.Enum):
    BUY = "buy"


class _Cat(BaseModel):
    kind: Literal["cat"]


class _Dog(BaseModel):
    kind: Literal["dog"]


class _Pet(BaseModel):
    pet: Annotated[_Cat | _Dog, Field(discriminator="kind")]


def _app() -> FastAPI:
    app = FastAPI()
    install_error_redaction(app)

    @app.get("/probe/{item_id}")
    async def probe(
        item_id: uuid.UUID,
        u4: UUID4,
        i: int,
        f: float,
        b: bool,
        d: Decimal,
        ts: dt.datetime,
        day: dt.date,
        tm: dt.time,
        span: dt.timedelta,
        side: _Side,
        lit: Literal["x", "y"],
        short: Annotated[str, Query(max_length=3)],
        pat: Annotated[str, Query(pattern=r"^[A-Z]{2}$")],
        pos: Annotated[int, Query(gt=0)],
    ) -> dict[str, Any]:
        return {}

    @app.post("/probe-body")
    async def probe_body(body: _Pet) -> dict[str, Any]:
        return {}

    return app


_CLIENT = TestClient(_app())
_PARAMS = "u4 i f b d ts day tm span side lit short pat pos".split()


def _messages(value: str) -> dict[tuple[str, str], str]:
    resp = _CLIENT.get(f"/probe/{value}", params=dict.fromkeys(_PARAMS, value))
    assert resp.status_code == 422
    return {(e["field"], e["rule"]): e["message"] for e in resp.json()["errors"]}


def _body_messages(value: str) -> dict[tuple[str, str], str]:
    resp = _CLIENT.post("/probe-body", json={"pet": {"kind": value}})
    assert resp.status_code == 422
    return {(e["field"], e["rule"]): e["message"] for e in resp.json()["errors"]}


@pytest.mark.parametrize("value", _VALUES)
def test_validation_message_input_characters_never_change_it(value: str) -> None:
    sent, twin = _messages(value), _messages(value.translate(_TWIN))
    assert sent.keys() == twin.keys()
    assert {k: m for k, m in sent.items() if twin[k] != m} == {}


def test_validation_message_union_tag_never_quotes_the_tag() -> None:
    twin = "G0kz-JQX-vvjg".translate(_TWIN)
    sent, other = _body_messages("G0kz-JQX-vvjg"), _body_messages(twin)
    assert sent == other
    assert list(sent.values()) == [CONSTANT_MESSAGES["union_tag_invalid"]]


def test_validation_message_union_tag_differed_before_the_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(error_redaction, "CONSTANT_MESSAGES", {})
    assert _body_messages("G0kz-JQX-vvjg") != _body_messages("G0kz-JQX-vvjg".translate(_TWIN))


def test_validation_message_uuid_parsing_is_the_constant() -> None:
    found = _messages("G0kz-JQX-vvjg")
    assert found[("path.item_id", "uuid_parsing")] == "Input should be a valid UUID."
    # closed: a new entry needs a probe here
    assert set(CONSTANT_MESSAGES) == {"uuid_parsing", "union_tag_invalid"}
