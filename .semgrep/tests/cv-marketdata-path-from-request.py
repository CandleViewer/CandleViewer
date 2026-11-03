"""Fixtures for cv-marketdata-path-from-request (E21-X02 G-06, SR-097)."""

import os
import pathlib
from pathlib import Path


def bad_join(root, symbol):
    return os.path.join(root, symbol, "heatmap_cells")  # ruleid: cv-marketdata-path-from-request


def bad_join_query_field(root, q):
    return os.path.join(root, q.symbol)  # ruleid: cv-marketdata-path-from-request


def bad_pathlib(root, symbol):
    return pathlib.Path(root, symbol)  # ruleid: cv-marketdata-path-from-request


def bad_slash(root: Path, symbol):
    return root / symbol  # ruleid: cv-marketdata-path-from-request


def bad_slash_fstring(root: Path, from_):
    return root / f"date={from_}"  # ruleid: cv-marketdata-path-from-request


def bad_open(request):
    return open(request.query_params["symbol"])  # ruleid: cv-marketdata-path-from-request


def good_registry(registry, stream, symbol):
    # The storage tier resolves a registered partition; this module builds no path.
    return registry.resolve_partition(stream, symbol)  # ok: cv-marketdata-path-from-request


def good_constant(root: Path):
    return root / "_manifests"  # ok: cv-marketdata-path-from-request


def good_division(size, natives):
    return float(size) / natives  # ok: cv-marketdata-path-from-request
