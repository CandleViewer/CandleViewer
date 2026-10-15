"""`net_binding_safe` is served on the scraped registry (#2496).

The gauge is module-level, so it lives on the library default registry, which no
`/metrics` endpoint serves; `export_net_metrics` re-exports it with `env`. Without
that, `NetBindingUnsafe` (`infra/prometheus/alerts/system_page.yml`) could never fire.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from prometheus_client import REGISTRY, generate_latest

from candleviewer.app import create_app
from candleviewer.net import (
    BindingSelfCheck,
    ReadOnlyGate,
    apply_self_check_result,
    export_net_metrics,
    net_binding_safe,
)
from candleviewer.net.metrics import NET_EXPORTED_NAMES
from candleviewer.observability.metrics import CollectorRegistry
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings

SERIES = "net_binding_safe"


@pytest.fixture
def _restore_gauge() -> Iterator[None]:
    """The gauge is process-wide; put back whatever the other tests left in it."""
    before = REGISTRY.get_sample_value(SERIES)
    yield
    net_binding_safe.set(before or 0.0)


def _scraped_after_check(bound: str) -> str:
    check = BindingSelfCheck(address_enumerator=lambda: [bound])
    apply_self_check_result(check.run(), read_only_gate=ReadOnlyGate(), gauge=net_binding_safe)
    registry = CollectorRegistry()
    collector = export_net_metrics(registry, env="demo")
    try:
        return generate_latest(registry).decode()
    finally:
        collector.close()


@pytest.mark.usefixtures("_restore_gauge")
def test_export_net_metrics_public_binding_serves_zero_with_env() -> None:
    text = _scraped_after_check("0.0.0.0:8000")

    assert f'{SERIES}{{env="demo"}} 0.0' in text
    assert f"# HELP {SERIES} " in text


@pytest.mark.usefixtures("_restore_gauge")
def test_export_net_metrics_loopback_binding_serves_one_with_env() -> None:
    text = _scraped_after_check("127.0.0.1:8000")

    assert f'{SERIES}{{env="demo"}} 1.0' in text


def test_net_binding_safe_is_catalogued_live_and_exported() -> None:
    spec = next(s for s in CATALOGUE if s.name == SERIES)

    assert (spec.kind, spec.labels, spec.status, spec.exported) == ("gauge", (), "live", True)
    assert frozenset({SERIES}) == NET_EXPORTED_NAMES


def test_create_app_serves_net_binding_safe_on_the_scraped_registry() -> None:
    app = create_app(Settings(environment=Environment.DEMO))

    text = generate_latest(app.state.app_context.metrics).decode()

    assert any(ln.startswith(f'{SERIES}{{env="demo"}} ') for ln in text.splitlines())
