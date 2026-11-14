"""E22-X02 (#756) harness: `GET /market/trades` as the app composes it (the trades router behind the
app's error redaction, so a refusal answers in the `22` problem shape) over the recorded
`publicTrade` tape (packages/fixtures, `clean_publicTrade_BTCUSDT`). No network, no socket."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.api.trades import make_trades_router
from candleviewer.orderflow.bigtrade_models import BigTradeConfig
from tests._bigtrades import Tape, recorded_batches

FLOOR = Decimal("0.001")


class Principal:
    def __init__(self, user: str, *, read: bool = True) -> None:
        self.user, self.read = user, read

    def has(self, permission: str) -> bool:
        return self.read and permission == "marketdata:read"


class Resolver:
    def __init__(self, principal: Principal | None) -> None:
        self.principal = principal

    async def resolve(self, request: Request) -> Any:
        return self.principal


def recorded_tape() -> Tape:
    return Tape([e for batch in recorded_batches() for e in batch])


def client(tape: Tape, principal: Principal | None = None) -> TestClient:
    app = FastAPI()
    install_error_redaction(app)
    app.include_router(
        make_trades_router(
            lambda: tape,
            principal_resolver=Resolver(principal or Principal("u1")),
            min_size_floor=lambda s: FLOOR if s == "BTCUSDT" else None,
            config=lambda _s: BigTradeConfig(),
        )
    )
    return TestClient(app)
