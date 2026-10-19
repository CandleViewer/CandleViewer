"""Selection rule for the ``e08_regression`` marker (E08-Q06 regression pack, #283).

`qa/plans/e08-regression-pack.md` says why each path is in the pack and maps every P0/P1 defect
fixed in E08 to the case that guards it; this module is the one place that says which paths the
marker covers, and `tests/conftest.py` applies it at collection time, next to the E09 pack's rule.
Same design as `tests/_e09_regression_pack.py`: tagging by path, not by a decorator per test,
leaves the suites other PRs edit untouched and lets a new test dropped into a pack directory join
the pack on its own. `tests/qa/test_e08_regression_pack.py` fails when this list and the pack
document's "Marker coverage" list differ in either direction, when the pack cites a test the
marker does not select, and when the marker selects anything the default lane deselects.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from functools import cache
from pathlib import Path
from typing import Final

import pytest

MARKER: Final = "e08_regression"
API_ROOT: Final = Path(__file__).resolve().parents[1]
# The E08-Q02 contract pack's directory is named after the venue its recorded corpus comes from.
# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
_CONTRACT_PACK: Final = "tests/contract/bybit/"

# A trailing slash means a directory, anything else one file. The pack document's "Marker
# coverage" section lists the same paths and says why each is in. The directories are the E08
# suites (adapter, ingestion, book, bus, corpus, E08-Q02 contract, E08-Q03 chaos, E08-X02 abuse
# cases); the single files are E08 routes and wiring that live in shared directories, the
# regression tests of P0/P1 defects fixed in E08 whose code sits in storage/ or bars/, and the
# E08-Q06 cross-epic handshake checks and promoted charter findings.
PACK_PATHS: Final[tuple[str, ...]] = (
    "tests/unit/exchange/",
    "tests/unit/ingestion/",
    "tests/unit/book/",
    "tests/unit/bus/",
    "tests/unit/fixtures_corpus/",
    _CONTRACT_PACK,
    "tests/chaos/ingestion/",
    "tests/security/ingestion/",
    "tests/unit/test_ingestion_service.py",
    "tests/unit/architecture/test_instrument_catalogue_composition.py",
    "tests/unit/api/test_instruments_router.py",
    "tests/unit/api/test_market_router.py",
    "tests/unit/api/test_market_klines_create_app.py",
    "tests/unit/api/test_orderbook_api.py",
    "tests/unit/api/test_trades_api.py",
    "tests/contract/test_market_klines_contract.py",
    # E08's statechart contract modules (B13 ws_conn, B14 book) and its instrument persistence.
    "tests/xstate_contract/test_b13_ws_conn.py",
    "tests/xstate_contract/test_b14_book.py",
    "tests/xstate_contract/test_b14_book_health.py",
    "tests/unit/migrations/test_0004_instruments.py",
    "tests/unit/storage/test_db_models.py",
    "tests/unit/storage/questdb/test_repository.py",
    "tests/unit/storage/questdb/test_bind_count_guards.py",
    "tests/unit/storage/questdb/test_schema_tag_parity.py",
    "tests/unit/storage/test_questdb_reader_kline_limit.py",
    "tests/unit/bars/test_tape_time_reader.py",
    "tests/unit/bars/test_kline_rows.py",
    "tests/unit/bars/test_production_factory.py",
    "tests/qa/test_e08_handshake.py",
    "tests/qa/test_e08_charter_findings.py",
    # Cross-epic contract suites the handshake relies on instead of repeating them.
    "tests/contract/ws/test_ws_topic_registry_as_built.py",
    "tests/contract/ws/test_ws_book_snapshot_contract.py",
    "tests/contract/test_openapi_conformance.py",
)

# `addopts` in pyproject.toml deselects these by default (nightly or wall-clock-budget lanes, and
# `flaky`: a quarantined test runs in no lane, C-9.3). A bare `-m e08_regression` replaces that
# default expression, so the marker is withheld from them. The guard fails when this set and that
# expression differ.
NIGHTLY_ONLY_MARKERS: Final = frozenset({"flaky", "fuzz", "harness", "perf"})
# Also withheld: `exchange_smoke`, E08-T05's manual smoke runs against the venue's demo host, which
# CI's `py` lane deselects too. No pack path holds one; if one lands there, the default lane still
# selects it, so the guard's whole-tree check reports it as missed by the marker.
WITHHELD_MARKERS: Final = NIGHTLY_ONLY_MARKERS | {"exchange_smoke"}


def is_pack_path(relative: str) -> bool:
    """`relative` is a POSIX path relative to services/api."""
    return any(
        relative.startswith(entry) if entry.endswith("/") else relative == entry
        for entry in PACK_PATHS
    )


def is_tagged(relative: str, marker_names: Collection[str]) -> bool:
    return is_pack_path(relative) and WITHHELD_MARKERS.isdisjoint(marker_names)


@cache
def _relative_to_api_root(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(API_ROOT).as_posix()
    except ValueError:
        return None


def tag_pack(items: Iterable[pytest.Item]) -> None:
    for item in items:
        relative = _relative_to_api_root(item.path)
        if relative is not None and is_tagged(relative, {m.name for m in item.iter_markers()}):
            item.add_marker(getattr(pytest.mark, MARKER))
