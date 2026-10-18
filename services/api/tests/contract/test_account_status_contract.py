"""Contract (E27-T04, #837): the `ExchangeAccount` read model as its provider (C-6.2). In each
state it serves, its JSON form merged into an account row validates against 22-api-openapi.yaml's
`ExchangeAccount` and the generated model, with exactly the five fields it owns, each declared
there, and nothing in `balance` or `health` that `WalletBalance` or `AccountHealth` does not
declare."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.accounts.status import AccountStatus
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from tests.unit.accounts._fakes import ACC, ACC_B
from tests.unit.accounts._status_world import StatusWorld

_SPEC: Any = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_ACCOUNT = Draft202012Validator(
    {"$ref": "urn:cv:openapi#/components/schemas/ExchangeAccount"},
    registry=Registry().with_resource(
        "urn:cv:openapi", Resource.from_contents(_SPEC, default_specification=DRAFT202012)
    ),
    format_checker=Draft202012Validator.FORMAT_CHECKER,
)
_ACC_C = UUID(int=3)
#: The `ExchangeAccount` fields the monitor and the wallet cache own; the row has the rest.
_OWNED = {"connection_state", "health", "balance", "balance_stale", "balance_stale_since"}
_ROW = {"id": str(ACC), "exchange": "bybit", "environment": "testnet", "kind": "main"}
_ROW |= {"label": "Main", "exchange_uid": "10234567"}


def _statuses() -> dict[str, AccountStatus]:
    """The read model in each state it serves, as #895 and #899 will merge it into a row."""
    world = StatusWorld()
    world.monitor.track(_ACC_C)
    world.wallets.track(_ACC_C)  # monitored, never connected: no heartbeat age, no balance
    world.monitor.ws_dropped(ACC_B)
    world.monitor.rest_ok(ACC_B)
    read = world.status
    now = {"connected": read(ACC), "degraded": read(ACC_B), "disabled": read(ACC, enabled=False)}
    now |= {"pending": read(UUID(int=4)), "never_connected": read(_ACC_C)}
    world.clock.advance(31)  # no evidence since: down, and the balances are stale
    return now | {"down_and_stale": read(ACC), "stale_without_a_balance": read(_ACC_C)}


_STATUSES = _statuses()


@pytest.mark.parametrize("state", sorted(_STATUSES))
def test_the_read_model_validates_as_an_exchange_account_with_its_five_fields(state: str) -> None:
    wire = _STATUSES[state].model_dump(mode="json")
    account = _ROW | wire
    assert set(wire) == _OWNED <= set(_SCHEMAS["ExchangeAccount"]["properties"])
    assert [error.message for error in _ACCOUNT.iter_errors(account)] == []
    generated = api.ExchangeAccount.model_validate(account)
    assert generated.model_dump(mode="json", exclude_unset=True, include=_OWNED) == wire


def test_the_read_model_serves_only_fields_the_balance_and_health_schemas_declare() -> None:
    wire = _STATUSES["degraded"].model_dump(mode="json")
    assert set(wire["balance"]) <= set(_SCHEMAS["WalletBalance"]["properties"])
    assert set(wire["health"]) == set(_SCHEMAS["AccountHealth"]["properties"])
    stale = _STATUSES["down_and_stale"].model_dump(mode="json")
    assert stale["balance_stale"] is True and stale["balance_stale_since"] is not None
