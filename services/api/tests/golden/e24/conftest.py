"""Shared fixtures for the E24-T06 parity tests: the reference is computed once per case."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.golden.e24 import _loader as L
from tests.golden.e24 import _reference as R

RefOf = Callable[[str], tuple[L.Rows, R.Ref]]


@pytest.fixture(scope="session")
def ref_of(tmp_path_factory: pytest.TempPathFactory) -> RefOf:
    """`ref_of(case_id)`: the case's rows and its DuckDB reference (Parquet under a tmp dir)."""
    cache: dict[str, tuple[L.Rows, R.Ref]] = {}

    def get(case_id: str) -> tuple[L.Rows, R.Ref]:
        if case_id not in cache:
            rows = L.build_rows(L.case_by_id(case_id))
            cache[case_id] = (rows, R.run(rows, tmp_path_factory.mktemp(case_id)))
        return cache[case_id]

    return get
