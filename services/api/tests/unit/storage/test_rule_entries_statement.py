"""E35-T12 slice 3e: the read of a rule's resting entries (`rule_entries_statement`; 24 §11.5
"Exits", §11.7; BQ-7, BQ-8, BQ-10), as it is rendered for Postgres: its rows are the rule's
groups' orders, through `origin_rule_id`, `placed`, open, not reduce-only, with no parent order,
in a group whose algo is `none`, of one environment; the account and the symbol narrow it only
when named; every value is a bound parameter, none spliced into the text. Its rows on Postgres
are the integration suite's (`test_rule_entries_read_pg.py`)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import asyncpg

from candleviewer.storage.repositories.orders_sqlalchemy import (
    RULE_ENTRY_STATES,
    SqlAlchemyOrderStore,
    rule_entries_statement,
)

RULE, ACCOUNT = uuid.UUID(int=0x51), uuid.UUID(int=0x52)
_PG = asyncpg.dialect()  # type: ignore[no-untyped-call]  # SQLAlchemy leaves the dialect untyped


def _sql(
    account: uuid.UUID | None = None, symbol: str | None = None
) -> tuple[str, dict[str, object]]:
    compiled = rule_entries_statement(RULE, "demo", account, symbol, 25).compile(dialect=_PG)
    return str(compiled), dict(compiled.params)


def test_the_read_selects_the_rules_resting_entries_through_its_groups() -> None:
    text, params = _sql()
    for clause in (
        "JOIN trade_group_legs ON orders.trade_group_leg_id = trade_group_legs.id",
        "JOIN trade_groups ON trade_group_legs.trade_group_id = trade_groups.id",
        "trade_groups.origin_rule_id = $",
        "trade_groups.env = $",
        "trade_groups.algo = $",
        "orders.provenance = $",
        "orders.reduce_only IS false",
        "orders.parent_order_id IS NULL",
        "orders.state IN (__[POSTCOMPILE_rule_open])",
        "ORDER BY orders.created_ts, orders.id",
    ):
        assert clause in text, clause
    assert (params["origin_rule_id_1"], params["env_1"]) == (RULE, "demo")
    assert (params["algo_1"], params["provenance_1"]) == ("none", "placed")
    assert "exchange_account_id =" not in text and "orders.symbol =" not in text
    assert str(RULE) not in text and "demo" not in text  # bound, never spliced
    assert set(RULE_ENTRY_STATES) == {
        "validated", "submitting", "submitted", "triggered", "partially_filled", "amend_pending",
    }  # fmt: skip


def test_an_account_and_a_symbol_narrow_the_read_when_named() -> None:
    text, params = _sql(ACCOUNT, "BTCUSDT")
    assert "orders.exchange_account_id = $" in text
    assert "orders.symbol = $" in text
    assert (params["exchange_account_id_1"], params["param_1"]) == (ACCOUNT, "BTCUSDT")
    assert "BTCUSDT" not in text


async def test_a_read_with_no_bound_is_refused_before_any_statement() -> None:
    store = SqlAlchemyOrderStore(object())  # type: ignore[arg-type]  # never reached: refused first
    for limit in (0, -1, True):
        with pytest.raises(ValueError, match="limit"):
            await store.rule_resting_entries(RULE, "demo", limit=limit)
