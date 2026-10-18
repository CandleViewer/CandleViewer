"""Pair proving the autouse structlog reset (#2057): test A configures logging; test B, ordered
after it, must see pristine structlog state. Test C runs the pair in a fresh session that also
collects a module importing `candleviewer.main` (#3357, #2519)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
import structlog
from structlog.testing import capture_logs

from candleviewer.observability.logging import configure_logging

_module_logger = structlog.get_logger("isolation-standin")
_API_ROOT = Path(__file__).resolve().parents[3]
_PAIR = tuple(
    f"{Path(__file__).relative_to(_API_ROOT).as_posix()}::{name}"
    for name in ("test_a_configure_logging_leaves_state_behind", "test_b_state_is_pristine_after_a")
)
# Its module imports `candleviewer.main`, so collecting it runs `configure_logging()`. Node ids
# only: pytest collects a `::` argument while resolving it, so the argument order is the
# collection order (a bare file argument would be collected after every `::` one).
_MAIN_IMPORTER = (
    "tests/unit/test_main_lifespan_stop_order.py"
    "::test_lifespan_stops_the_ws_gateway_before_anything_else"
)


def test_a_configure_logging_leaves_state_behind() -> None:
    configure_logging(env="demo")
    # Function-local logger: a module-level one first used here would be pinned by the cache,
    # which no reset can undo (that is why production modules resolve loggers per call).
    structlog.get_logger("isolation-a").info("emitted_under_configured_logging")
    assert structlog.is_configured()
    assert structlog.contextvars.get_contextvars() == {"env": "demo"}


def test_b_state_is_pristine_after_a() -> None:
    assert not structlog.is_configured()
    assert structlog.contextvars.get_contextvars() == {}
    assert not any(type(h).__name__ == "_RawQueueHandler" for h in logging.getLogger().handlers)
    with capture_logs() as logs:
        _module_logger.info("fresh_emit")
    assert [e["event"] for e in logs] == ["fresh_emit"]


@pytest.mark.parametrize(
    "order",
    [
        pytest.param((_MAIN_IMPORTER, *_PAIR), id="main-importer-collected-first"),
        pytest.param((_PAIR[1], _MAIN_IMPORTER), id="pristine-check-runs-first"),
    ],
)
def test_c_the_pair_passes_when_collection_imports_candleviewer_main(
    order: tuple[str, ...], tmp_path: Path
) -> None:
    """Collecting `candleviewer.main` configures logging before any fixture can undo it. Collected
    first, pytest's `__test__` probe then pinned `_module_logger` to that chain, so B captured
    nothing; collected last, B ran first under it. A fresh session makes the collection order
    this test's own, whatever order the outer run collects in."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(_API_ROOT)
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly"]
    done = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter, pytest, literal node ids
        [*argv, "--no-cov", f"--basetemp={tmp_path / 'inner'}", *order],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=_API_ROOT,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
