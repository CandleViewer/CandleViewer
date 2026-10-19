r"""E08-Q06 cross-epic handshake checks (#283): the E08 contracts downstream epics build on.

E12 (bars), E17 (WS gateway), E22 (tape), E24 (derivatives) and E29 (OMS) start from these. Offline
and in-process, so a downstream epic re-runs them at its start, with the suites they rely on (all
of them are in the E08 regression pack as well):

    cd services/api && uv run pytest -p no:randomly --no-cov tests/qa/test_e08_handshake.py \
        tests/unit/exchange/test_market_data_port_spec.py \
        tests/contract/ws/test_ws_topic_registry_as_built.py \
        tests/contract/bybit/test_pipeline_read_surface.py \
        tests/contract/test_market_klines_contract.py tests/contract/test_openapi_conformance.py

Each check holds the code to the document that owns the contract. What another suite already pins
is not repeated here: the port method set (`tests/unit/exchange/test_market_data_port_spec.py`),
the 23 §6.1 table against the topic registry
(`tests/contract/ws/test_ws_topic_registry_as_built.py`), the trades, order book, ticker and klines
bodies against the generated OpenAPI models (`tests/contract/bybit/test_pipeline_read_surface.py`,
`tests/contract/test_market_klines_contract.py`) and served routes against declared operations
(`tests/contract/test_openapi_conformance.py`). The command above runs every one of them, and
`test_the_rerun_command_runs_every_suite_this_module_relies_on` keeps it that way.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import re
import typing
import warnings
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from candleviewer.api._generated.openapi_models import (
    Instrument as InstrumentBody,
)
from candleviewer.api._generated.openapi_models import (
    InstrumentDetail,
    InstrumentsPageMeta,
    Page,
)
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.instruments import InstrumentsPrincipal, make_instruments_router
from candleviewer.book.models import BookStatus
from candleviewer.book.tiers import DEFAULT_DEPTH
from candleviewer.domain.events import (
    DomainEvent,
    Instrument,
    InstrumentUpdatedEvent,
    MarketEvent,
)
from candleviewer.exchange.base.models import (
    BookDelta,
    BookSnapshot,
    FundingEvent,
    KlineEvent,
    LiquidationEvent,
    OpenInterestEvent,
    TickerEvent,
    TradeEvent,
)
from candleviewer.exchange.base.ports import MarketDataPort, TradingPort
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.ingestion.instruments import CatalogueSnapshot
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import GapEvent, TradeStream
from candleviewer.ingestion.watchdog import FeedHealthEvent
from candleviewer.orderbook_wiring import BookStream
from candleviewer.ws.topics import DEPTHS, FAMILIES

# `_Demand` is ws_wiring's private lease protocol (E17-S02) and has no public name. If E17
# renames it, this module fails at import, not with a contract message: point the lease check
# (`test_c_e08_streams_take_the_lease_calls_the_ws_gateway_makes`) at the new name.
from candleviewer.ws_wiring import _Demand, ingestion_streams
from tests._corpus import rest
from tests._e08_regression_pack import is_pack_path
from tests.openapi_helpers import deref

API_ROOT: Final = Path(__file__).resolve().parents[2]
PLAN: Final = API_ROOT.parents[1] / "docs" / "plan"
SCHEMAS_DOC: Final = PLAN / "24-internal-schemas.md"
PACKAGE: Final = API_ROOT / "candleviewer"

# 24 §2.1-2.7: the families the adapter emits, plus §2.8's metadata-change event.
MARKET_FAMILIES: Final = (
    TradeEvent,
    BookSnapshot,
    BookDelta,
    TickerEvent,
    KlineEvent,
    LiquidationEvent,
    OpenInterestEvent,
    FundingEvent,
)
# Drift D1 (docs/qa/e08-signoff.md): E08 publishes these on the bus without the 24 §1.1 C6
# envelope (`schema_version`, `event_id`, `ts_event`, `ts_ingest`) that C6 asks of every bus event.
# Pinned so the record cannot go stale: adding the envelope to one fails the check below, and the
# fix then removes it here and updates the evidence pack.
UNVERSIONED_CONTROL_PAYLOADS: Final = (BookStatus, GapEvent, FeedHealthEvent)
# (domain, detail) of every bus topic E08 publishes -> how 24 §2.9 "As shipped" spells it.
E08_BUS_TOPICS: Final[Mapping[tuple[str, str], str]] = {
    ("md", "trade"): "`trade`",
    ("md", "book"): "`book`",
    ("md", "ticker"): "`ticker`",
    ("md", "gap"): "`gap`",
    ("health", "feed"): "`{env}.health.feed`",
    ("instruments", "updated"): "`{env}.instruments.{symbol}.updated`",
}
E08_MODULES: Final = ("ingestion/", "book/", "orderbook_wiring.py")
# The WS family -> the ingestion stream that holds its upstream demand (ws_wiring, E17-S02).
E08_FED_FAMILIES: Final = {
    "trades": "trades",
    "bars": "trades",
    "book": "books",
    "ticker": "tickers",
}


def _hints(member: Callable[..., object]) -> dict[str, Any]:
    return typing.get_type_hints(member)


def _mentions_any(annotation: object) -> bool:
    if annotation is Any:
        return True
    return any(_mentions_any(arg) for arg in typing.get_args(annotation))


def _public_methods(port: type) -> Iterator[tuple[str, Callable[..., object]]]:
    for name, member in vars(port).items():
        if not name.startswith("_") and callable(member):
            yield name, member


@pytest.mark.parametrize("port", [MarketDataPort, TradingPort], ids=lambda p: p.__name__)
def test_a_every_port_method_is_fully_annotated_and_never_any(port: type) -> None:
    """24 §14.1: downstream epics code against these signatures (E29 against `TradingPort`)."""
    problems = []
    for name, method in _public_methods(port):
        hints = _hints(method)
        params = [p for p in inspect.signature(method).parameters if p != "self"]
        if "return" not in hints:
            problems.append(f"{name}: no return annotation")
        problems += [f"{name}({p}): not annotated" for p in params if p not in hints]
        problems += [f"{name}: {k} is Any" for k, v in hints.items() if _mentions_any(v)]

    assert list(_public_methods(port)), f"{port.__name__} declares no methods"
    assert not problems, "\n".join(problems)


def _envelope_block() -> str:
    text = SCHEMAS_DOC.read_text(encoding="utf-8")
    section = text[text.index("### 1.4 Base envelope") :]
    match = re.search(r"```python\n(.*?)```", section, flags=re.DOTALL)
    assert match is not None, "24 §1.4 no longer holds the envelope code block"
    return match.group(1)


def _doc_fields(block: str, cls: str) -> set[str]:
    """Field names the doc's `class <cls>(...)` declares (its own, not inherited)."""
    body = re.search(rf"^class {cls}\(.*?\):\n(.*?)(?=^\S|\Z)", block, flags=re.M | re.S)
    assert body is not None, f"24 §1.4 no longer declares {cls}"
    names = re.findall(r"^    (\w+)\s*:", body.group(1), flags=re.M)
    return {n for n in names if n != "model_config"}


def _own_fields(model: type[BaseModel], base: type[BaseModel]) -> set[str]:
    return set(model.model_fields) - set(base.model_fields)


def test_b_the_bus_event_envelope_is_the_one_24_section_1_4_declares() -> None:
    block = _envelope_block()

    assert set(DomainEvent.model_fields) == _doc_fields(block, "DomainEvent")
    assert _own_fields(MarketEvent, DomainEvent) == _doc_fields(block, "MarketEvent")
    assert DomainEvent.model_fields["schema_version"].default == 1


@pytest.mark.parametrize(
    "model", [*MARKET_FAMILIES, InstrumentUpdatedEvent], ids=lambda m: m.__name__
)
def test_b_every_event_family_e08_emits_is_versioned_frozen_and_closed(
    model: type[BaseModel],
) -> None:
    """24 §1.1 C6 (a version lets consumers reject unknown shapes) and §17.1 (bus events)."""
    assert issubclass(model, DomainEvent)
    assert model is InstrumentUpdatedEvent or issubclass(model, MarketEvent)
    assert model.model_fields["schema_version"].default == 1
    assert model.model_config.get("frozen") is True
    assert model.model_config.get("extra") == "forbid"


@pytest.mark.parametrize("payload", UNVERSIONED_CONTROL_PAYLOADS, ids=lambda p: p.__name__)
def test_b_the_control_payloads_without_the_c6_envelope_are_exactly_drift_d1(payload: type) -> None:
    if issubclass(payload, BaseModel):
        fields = set(payload.model_fields)
    else:
        assert dataclasses.is_dataclass(payload), f"{payload.__name__}: neither model nor dataclass"
        fields = {f.name for f in dataclasses.fields(payload)}

    assert "schema_version" not in fields, (
        f"{payload.__name__} now carries schema_version: drift D1 is resolved for it, so drop it "
        "from UNVERSIONED_CONTROL_PAYLOADS and update docs/qa/e08-signoff.md"
    )


def _topics_built(path: Path) -> Iterator[tuple[str, str | None, str]]:
    """(domain, detail, call) of every literal `Topic(...)`/`TopicPattern(...)` in `path`."""
    with warnings.catch_warnings():
        # An applied migration (C-5.4: immutable) holds a SQL `\:` escape that 3.14 warns about.
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name not in ("Topic", "TopicPattern"):
            continue
        literal = {
            k.arg: k.value.value
            for k in node.keywords
            if isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)
        }
        domain = literal.get("domain")
        if domain is not None:
            yield domain, literal.get("detail"), name


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def _is_e08_module(relative: str) -> bool:
    return any(relative.startswith(prefix) for prefix in E08_MODULES)


def test_c_e08_publishes_exactly_the_bus_topics_24_section_2_9_lists_as_shipped() -> None:
    """Counts E08's modules plus `app.py`, which composes the catalogue refresh and publishes
    `instruments.{symbol}.updated` for it. Every literal `Topic(...)` in `app.py` with domain md,
    health or instruments is counted as E08's, and only keyword literals are seen: a topic another
    epic adds there in those domains fails here, so publish it from that epic's module instead."""
    published = {
        (domain, detail)
        for path in PACKAGE.rglob("*.py")
        if _is_e08_module(_relative(path)) or _relative(path) == "app.py"
        for domain, detail, call in _topics_built(path)
        if call == "Topic" and domain in {"md", "health", "instruments"}
    }
    text = SCHEMAS_DOC.read_text(encoding="utf-8")
    as_shipped = text[text.index("**As shipped (E08-T06 reconciliation") :].split("\n\n", 1)[0]
    undocumented = sorted(spelt for spelt in E08_BUS_TOPICS.values() if spelt not in as_shipped)

    assert published == set(E08_BUS_TOPICS)
    assert not undocumented, f"24 §2.9 'As shipped' does not list: {undocumented}"


def test_c_every_market_data_topic_another_module_uses_is_one_e08_publishes() -> None:
    """E12's builders subscribe to the tape here; a renamed detail would leave them silent."""
    foreign = {
        (_relative(path), domain, detail)
        for path in PACKAGE.rglob("*.py")
        if "_generated" not in path.parts and not _is_e08_module(_relative(path))
        for domain, detail, _ in _topics_built(path)
        if domain in {"md", "instruments"}
    }
    unknown = sorted(f"{path}: {d}.{x}" for path, d, x in foreign if (d, x) not in E08_BUS_TOPICS)

    assert ("bars/builder_set.py", "md", "trade") in foreign
    assert not unknown, f"market-data topics no E08 module publishes: {unknown}"


def test_c_the_ws_families_e08_feeds_lease_its_ingestion_streams() -> None:
    """23 §6.1 families (the registry, held to the table by the registry test) -> E08 streams."""
    streams = {"trades": object(), "books": object(), "tickers": object()}
    ctx: Any = SimpleNamespace(ingestion=SimpleNamespace(**streams))  # only `.ingestion` is read
    resolve = ingestion_streams(ctx)

    for family in FAMILIES:
        expected = E08_FED_FAMILIES.get(family)
        assert resolve(family) is (streams[expected] if expected else None), family


@pytest.mark.parametrize(
    "stream", [TradeStream, BookStream, TickerStream], ids=lambda s: s.__name__
)
@pytest.mark.parametrize("method", ["acquire", "release"])
def test_c_e08_streams_take_the_lease_calls_the_ws_gateway_makes(stream: type, method: str) -> None:
    assert _hints(getattr(stream, method)) == _hints(getattr(_Demand, method))


def test_c_e08s_book_tier_is_a_depth_the_ws_book_topic_offers() -> None:
    """23 §7.7: a `book` snapshot serves min(depth, tier) levels, so the tier must be offered."""
    assert DEFAULT_DEPTH in DEPTHS


# ---- (d) REST bodies E08 serves, against 22-api-openapi.yaml -------------------------------------

_FETCHED_US: Final = 1_700_000_000_000_000


def _properties(schema: Mapping[str, Any]) -> set[str]:
    """Declared property names of a dereferenced schema, `allOf` members merged."""
    names = set(schema.get("properties", {}))
    for member in schema.get("allOf", []):
        names |= _properties(member)
    return names


@pytest.fixture(scope="module")
def schemas() -> Callable[[str], Mapping[str, Any]]:
    """22-api-openapi.yaml component schemas by name, every `$ref` inlined."""
    spec: Mapping[str, Any] = load_openapi_spec()

    def schema(name: str) -> Mapping[str, Any]:
        resolved: Mapping[str, Any] = deref(spec, spec["components"]["schemas"][name])
        return resolved

    return schema


class _Reader:
    def __init__(self, snapshot: CatalogueSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> CatalogueSnapshot:
        return self._snapshot

    async def ensure_symbol(self, symbol: str) -> Instrument | None:
        return self._snapshot.get(symbol)


class _Viewer:
    def resolve(self, request: Request) -> InstrumentsPrincipal:
        return InstrumentsPrincipal(user_id="qa", permissions=frozenset({"instruments:read"}))


@pytest.fixture(scope="module")
def client() -> TestClient:
    rows = rest("rest/instruments_before.json")["result"]["list"]
    parsed = parse_instruments(rows, fetched_at_us=_FETCHED_US)
    assert parsed.instruments and not parsed.rejected
    snapshot = CatalogueSnapshot({i.symbol: i for i in parsed.instruments}, _FETCHED_US)
    app = FastAPI()
    app.include_router(
        make_instruments_router(
            lambda: _Reader(snapshot),
            principal_resolver=_Viewer(),
            now_us=lambda: _FETCHED_US + 60_000_000,
        )
    )
    return TestClient(app)


def test_d_list_instruments_body_is_the_22_api_page_of_instruments(
    client: TestClient, schemas: Callable[[str], Mapping[str, Any]]
) -> None:
    """The generated models ignore undeclared keys, so the key sets are compared as well."""
    response = client.get("/instruments")
    body = response.json()
    item_keys = set().union(*(set(item) for item in body["items"]))

    assert response.status_code == 200
    Page.model_validate(body)
    InstrumentsPageMeta.model_validate(body["meta"])
    assert [InstrumentBody.model_validate(item) for item in body["items"]]
    assert set(body["meta"]) <= _properties(schemas("InstrumentsPageMeta"))
    assert item_keys <= _properties(schemas("Instrument"))


def test_d_instrument_detail_body_is_the_22_api_instrument_detail(
    client: TestClient, schemas: Callable[[str], Mapping[str, Any]]
) -> None:
    response = client.get("/instruments/BTCUSDT")
    body = response.json()

    assert response.status_code == 200
    InstrumentDetail.model_validate(body)
    assert set(body) <= _properties(schemas("InstrumentDetail"))
    assert set(schemas("Instrument")["required"]) <= set(body)


def test_the_rerun_command_runs_every_suite_this_module_relies_on() -> None:
    """A downstream epic copies the docstring's command, so it must name every suite cited there."""
    doc = __doc__ or ""
    command = re.search(r"^    (cd services/api && .*?)\n\n", doc, flags=re.DOTALL | re.MULTILINE)
    assert command is not None, "the module docstring lost its re-run command"
    in_command = {word for word in command.group(1).split() if word.startswith("tests/")}
    cited = set(re.findall(r"`(tests/[^`]+\.py)`", doc)) | {"tests/qa/test_e08_handshake.py"}

    assert cited <= in_command, f"cited but not in the re-run command: {sorted(cited - in_command)}"
    assert all((API_ROOT / path).is_file() for path in in_command), sorted(in_command)
    assert all(is_pack_path(path) for path in in_command), "a re-run suite left the E08 pack"
