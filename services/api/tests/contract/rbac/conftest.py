"""Shared fixtures + the per-group timing summary and optional HTML artefact (E09-Q03)."""

from __future__ import annotations

import html
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.contract.rbac.rbac_harness import (
    CELLS,
    MATRIX_PATH,
    TIMINGS,
    World,
    build_world,
)


@pytest.fixture(scope="session")
def matrix() -> dict[str, Any]:
    with MATRIX_PATH.open(encoding="utf-8") as fh:
        loaded: dict[str, Any] = yaml.safe_load(fh)
    return loaded


@pytest.fixture(scope="module")
def _world_module(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    """The real-app world, built once per test module of this pack.

    `app.py` has no injection seam for the identity provider or the alert repository, so the two
    module-level names are patched. The patches MUST NOT outlive this package (C-13.7: no shared
    mutable global state), so they are applied through an explicit `MonkeyPatch` that is undone in
    a `finally` at module teardown, and `test_zz_patches_do_not_leak.py` asserts it afterwards. The
    same `MonkeyPatch` sets the `WORLD_ENV` variables, among them a per-module tmp root for the bars
    state blobs, so no cell reads the production default.
    Module scope is deliberate: this directory has no `__init__.py`, so pytest has no Package node
    and `scope="package"` would silently behave like `session` and leak into every later test.
    """
    mp = pytest.MonkeyPatch()
    try:
        yield build_world(mp, bars_state_root=tmp_path_factory.mktemp("bars-state"))
    finally:
        mp.undo()


@pytest.fixture
def world(_world_module: World) -> World:
    """The shared real-app world, reset to a clean state before every test."""
    w = _world_module
    w.rule_store._rows.clear()
    w.scope_events.clear()
    w.audit.records.clear()
    w.purge_backend.calls.clear()
    w.step_up.elevated = True
    w.resolver.revoked.clear()
    for actor_uid in list(w.users.roles):
        w.users.roles[actor_uid] = w.users.initial_roles[actor_uid]
    return w


def pytest_terminal_summary(terminalreporter: Any) -> None:
    if not TIMINGS:
        return
    terminalreporter.section("rbac-matrix per-group timing")
    for group, secs in sorted(TIMINGS.items()):
        terminalreporter.write_line(f"{group:<28} {len(secs):>4} cells  {sum(secs):6.2f}s")
    out = os.environ.get("CV_RBAC_MATRIX_REPORT")
    if out:
        rows = "".join(
            f"<tr><td>{html.escape(k.split('|')[0])}</td><td>{html.escape(k.split('|')[1])}</td>"
            f"<td class='{v}'>{v}</td></tr>"
            for k, v in sorted(CELLS.items())
        )
        Path(out).write_text(
            "<!doctype html><meta charset=utf-8><title>RBAC matrix</title>"
            "<style>.pass{background:#cfc}.xfail{background:#fe9}.fail{background:#fcc}</style>"
            f"<table><tr><th>operation</th><th>actor</th><th>result</th></tr>{rows}</table>",
            encoding="utf-8",
        )
