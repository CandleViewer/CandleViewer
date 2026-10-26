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
from pydantic import UUID4

from candleviewer.api.error_redaction import CONSTANT_MESSAGES, install_error_redaction

#: Letters no probed parser reads (exponent, duration unit, inf/nan, boolean), digits shifted by 5.
_TWIN = str.maketrans("GJKQVXZgjkqvz0123456789", "QXZGJKVqvzgjk5678901234")
_VALUES = ("G0kz-JQX-vvjg", "2026-13-45", "9" * 40, "zq-12345678-1234-1234-1234", "1" * 31 + "Kj")


class _Side(enum.Enum):
    BUY = "buy"


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

    return app


_CLIENT = TestClient(_app())
_PARAMS = "u4 i f b d ts day tm span side lit short pat pos".split()


def _messages(value: str) -> dict[tuple[str, str], str]:
    resp = _CLIENT.get(f"/probe/{value}", params=dict.fromkeys(_PARAMS, value))
    assert resp.status_code == 422
    return {(e["field"], e["rule"]): e["message"] for e in resp.json()["errors"]}


@pytest.mark.parametrize("value", _VALUES)
def test_validation_message_input_characters_never_change_it(value: str) -> None:
    sent, twin = _messages(value), _messages(value.translate(_TWIN))
    assert sent.keys() == twin.keys()
    assert {k: m for k, m in sent.items() if twin[k] != m} == {}


def test_validation_message_uuid_parsing_is_the_constant() -> None:
    found = _messages("G0kz-JQX-vvjg")
    assert found[("path.item_id", "uuid_parsing")] == "Input should be a valid UUID."
    assert set(CONSTANT_MESSAGES) == {"uuid_parsing"}  # closed: a new entry needs a probe here
