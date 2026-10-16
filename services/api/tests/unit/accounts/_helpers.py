"""Shared key-verification inputs for the accounts tests (E27-T03, #836).

The documented-shape replies in `tests/fixtures/key_verification/` (its README names source,
date, env and redaction), parsed by the adapter, with the clock and egress IP they are pinned to.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from candleviewer.exchange.bybit.key_info import (
    ApiKeyFacts,
    ProbeFacts,
    parse_key_info,
    parse_probe,
)
from tests.unit.accounts._permission_cases import BASE

FIXTURES = Path(__file__).parents[2] / "fixtures" / "key_verification"
NOW = datetime(2026, 10, 15, 9, tzinfo=UTC)
T = 1792054800000  # the fixtures' exchange clock, NOW in epoch ms
EGRESS = "203.0.113.7"
WITHDRAW = {**BASE, "Wallet": ["Withdraw"]}


def load(name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return body


def facts(**result: Any) -> ApiKeyFacts:
    body = copy.deepcopy(load("key_info_trade.json"))
    body["result"].update(result)
    return parse_key_info(body)


def probed(sent: int = T - 50, received: int = T + 50) -> ProbeFacts:
    return parse_probe(load("wallet_balance.json"), sent_at_ms=sent, received_at_ms=received)
